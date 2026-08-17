import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const origin = "http://127.0.0.1:8093";
const controlToken = "phase2-lifecycle-test-control-token-0001";
const controlHeader = "x-searise-lifecycle-token";
const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const appBuild = { A: "phase2-lifecycle-a", B: "phase2-lifecycle-b", C: "phase2-lifecycle-c" } as const;
type Deployment = keyof typeof appBuild;
type BrowserRequest = { method: string; path: string };

type WorkerIdentity = Readonly<{
  type: "worker-identity";
  pair: Readonly<{ contractVersion: 1; appBuildId: string; dataReleaseId: string }>;
  precacheSetSha256: string;
}>;

test.afterEach(async () => {
  await fetch(`${origin}/__lifecycle/network`, {
    method: "POST",
    headers: { [controlHeader]: controlToken, "content-type": "application/json" },
    body: JSON.stringify({ offline: false }),
  }).catch(() => undefined);
});

async function control(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${origin}/__lifecycle/${path}`, {
    ...init,
    headers: { [controlHeader]: controlToken, ...(init.headers ?? {}) },
  });
}

async function selectDeployment(deployment: Deployment): Promise<void> {
  const response = await control("deployment", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ deployment }),
  });
  expect(response.ok, await response.text()).toBe(true);
}

async function setNetworkOffline(offline: boolean): Promise<void> {
  const response = await control("network", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ offline }),
  });
  expect(response.ok, await response.text()).toBe(true);
}

async function serverRequests(): Promise<readonly Readonly<{ path: string; status: number }>[]> {
  const response = await control("state");
  expect(response.ok).toBe(true);
  return (await response.json() as { requests: readonly Readonly<{ path: string; status: number }>[] }).requests;
}

async function workerIdentity(page: Page, target: "controller" | "waiting"): Promise<WorkerIdentity | null> {
  return page.evaluate(async (kind) => {
    const registration = await navigator.serviceWorker.getRegistration("/");
    const worker = kind === "controller" ? navigator.serviceWorker.controller : registration?.waiting;
    if (!worker) return null;
    const messageToken = `journey-${crypto.randomUUID()}`;
    const channel = new MessageChannel();
    return new Promise<WorkerIdentity>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error(`${kind} identity timed out`)), 5_000);
      channel.port1.onmessage = ({ data }) => {
        window.clearTimeout(timeout);
        channel.port1.close();
        resolve(data as WorkerIdentity);
      };
      worker.postMessage({
        protocol: "searise-offline-worker-v1",
        type: "discover-identity",
        messageToken,
      }, [channel.port2]);
    });
  }, target);
}

async function expectIdentity(page: Page, target: "controller" | "waiting", deployment: Deployment): Promise<void> {
  await expect.poll(() => workerIdentity(page, target)).toMatchObject({
    type: "worker-identity",
    pair: { appBuildId: appBuild[deployment], dataReleaseId: releaseId },
  });
}

async function bootInitialA(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  await expect.poll(() => page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration("/");
    return {
      active: registration?.active?.state ?? null,
      installing: registration?.installing?.state ?? null,
      waiting: registration?.waiting?.state ?? null,
    };
  })).toMatchObject({ active: "activated" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expectIdentity(page, "controller", "A");
}

async function warmAssessment(page: Page): Promise<void> {
  const search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  await search.fill("Málaga");
  await expect(page.getByRole("option", { name: /Málaga.*Andalucía, ES/i })).toBeVisible();
  await page.getByRole("option", { name: /Málaga.*Andalucía, ES/i }).click();
  await expect(page.locator(".projection-panel")).toHaveAttribute("data-phase", "result");
  await expect(page.locator(".projection-panel__outcome")).toHaveAttribute("data-outcome", "ProjectionAvailable");
}

async function installWaiting(page: Page, deployment: Deployment): Promise<void> {
  await selectDeployment(deployment);
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration("/");
    if (!registration) throw new Error("Service-worker registration is unavailable.");
    await registration.update();
  });
  await expectIdentity(page, "waiting", deployment);
}

async function prepareUpdate(page: Page, second: Page, current: Deployment, next: Deployment): Promise<void> {
  await expectIdentity(page, "controller", current);
  await expectIdentity(page, "waiting", next);
  await second.goto("/");
  await expect(second.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  await expectIdentity(second, "controller", current);
  const controller = await workerIdentity(second, "controller");
  const snapshot = await storageSnapshot(second);
  const currentRecord = lifecycleRecord(snapshot, current);
  expect(currentRecord).toMatchObject({
    state: "active",
    acceptedIdentity: { precacheSetSha256: controller?.precacheSetSha256 },
  });
  const update = second.locator('[data-update-state="update-available"]');
  await expect(update).toBeVisible();
  await update.getByRole("button", { name: "Prepare update" }).click();
  await expect.poll(() => second.evaluate(() => JSON.parse(
    localStorage.getItem("searise:update-intent:v1") ?? "null",
  )?.state)).toBe("armed");
  await expect(second.locator('[data-update-state="ready-to-activate"]')).toBeVisible();
}

function observeBrowserRequests(context: BrowserContext, requests: BrowserRequest[]): void {
  context.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin === origin) requests.push({ method: request.method(), path: url.pathname });
  });
}

async function naturallyActivate(
  context: BrowserContext,
  deployment: Deployment,
): Promise<Page> {
  await new Promise((resolve) => setTimeout(resolve, 750));
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const probe = await context.newPage();
    let activated = false;
    try {
      // Probe controller activation on a same-origin control document that
      // does not execute either deployment's application bundle. Loading `/`
      // here could start an old shell under the newly activated worker and
      // correctly trip mixed-authority fresh-boot protection.
      await probe.goto("/lifecycle-probe.html", { waitUntil: "domcontentloaded" });
      await probe.evaluate(() => navigator.serviceWorker.ready);
      if (!await workerIdentity(probe, "controller")) {
        await probe.reload({ waitUntil: "domcontentloaded" });
      }
      const identity = await workerIdentity(probe, "controller");
      if (identity?.pair.appBuildId === appBuild[deployment]) {
        activated = true;
        // The activation probe may have begun loading before the new worker
        // gained control. Close it and create a distinct launch boot under the
        // already verified controller.
        await probe.close();
        const fresh = await context.newPage();
        await fresh.goto("/", { waitUntil: "domcontentloaded" });
        await expectIdentity(fresh, "controller", deployment);
        await expect(fresh.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
        return fresh;
      }
    } finally {
      if (!activated) await probe.close();
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Deployment ${deployment} did not activate naturally after all controlled pages closed.`);
}

type StorageSnapshot = Readonly<{
  cacheNames: readonly string[];
  records: readonly Readonly<{ database: string; store: string; values: readonly unknown[] }>[];
}>;

async function storageSnapshot(page: Page): Promise<StorageSnapshot> {
  return page.evaluate(async () => {
    const records: { database: string; store: string; values: unknown[] }[] = [];
    for (const { name } of await indexedDB.databases()) {
      if (!name?.startsWith("searise-offline:")) continue;
      const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open(name);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        for (const store of Array.from(database.objectStoreNames)) {
          const values = await new Promise<unknown[]>((resolve, reject) => {
            const request = database.transaction(store, "readonly").objectStore(store).getAll();
            request.onsuccess = () => resolve(request.result as unknown[]);
            request.onerror = () => reject(request.error);
          });
          records.push({ database: name, store, values });
        }
      } finally {
        database.close();
      }
    }
    return { cacheNames: await caches.keys(), records };
  });
}

function lifecycleState(snapshot: StorageSnapshot, deployment: Deployment): string | undefined {
  return lifecycleRecord(snapshot, deployment)?.state;
}

function lifecycleRecord(snapshot: StorageSnapshot, deployment: Deployment): Readonly<{
  state?: string;
  acceptedIdentity?: Readonly<{ precacheSetSha256?: string; resourcePlanSha256?: string; receiptSha256?: string }>;
}> | undefined {
  const values = snapshot.records.find(({ database, store }) =>
    database === "searise-offline:lifecycle:v1" && store === "pair-lifecycle")?.values ?? [];
  return (values as { record?: {
    pair?: { appBuildId?: string };
    state?: string;
    acceptedIdentity?: { precacheSetSha256?: string; resourcePlanSha256?: string; receiptSha256?: string };
  } }[])
    .find(({ record }) => record?.pair?.appBuildId === appBuild[deployment])?.record;
}

test("rotates A to B to C naturally, retains two generations, and reloads C offline", async ({ context, page }, testInfo) => {
  const browserRequests: BrowserRequest[] = [];
  observeBrowserRequests(context, browserRequests);
  await selectDeployment("A");
  const initialRequestCount = (await serverRequests()).length;
  await bootInitialA(page);
  await warmAssessment(page);

  await installWaiting(page, "B");
  const secondA = await context.newPage();
  await prepareUpdate(page, secondA, "A", "B");
  await Promise.all([page.close(), secondA.close()]);
  let active = await naturallyActivate(context, "B");
  await warmAssessment(active);
  await expect.poll(() => active.evaluate(() => JSON.parse(
    localStorage.getItem("searise:update-intent:v1") ?? "null",
  )?.state)).toBe("consumed");

  await installWaiting(active, "C");
  const secondB = await context.newPage();
  await prepareUpdate(active, secondB, "B", "C");
  await Promise.all([active.close(), secondB.close()]);
  active = await naturallyActivate(context, "C");
  await warmAssessment(active);

  await expect.poll(async () => {
    const snapshot = await storageSnapshot(active);
    return {
      A: lifecycleState(snapshot, "A"),
      B: lifecycleState(snapshot, "B"),
      C: lifecycleState(snapshot, "C"),
      cacheA: snapshot.cacheNames.some((name) => name.includes(appBuild.A)),
    };
  }).toEqual({ A: undefined, B: "previous", C: "active", cacheA: false });
  const retained = await storageSnapshot(active);
  expect(retained.cacheNames.some((name) => name.includes(appBuild.C))).toBe(true);
  expect(retained.cacheNames.some((name) => name.includes(appBuild.B))).toBe(true);
  expect(retained.cacheNames.some((name) => name.includes(appBuild.A))).toBe(false);
  expect(lifecycleState(retained, "A")).toBeUndefined();
  for (const record of retained.records.filter(({ store }) => store !== "cleanup-fences")) {
    expect(JSON.stringify(record.values)).not.toContain(appBuild.A);
  }

  await active.close();
  await setNetworkOffline(true);
  active = await context.newPage();
  await active.goto("/", { waitUntil: "domcontentloaded" });
  await expect(active.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  await warmAssessment(active);
  await active.getByRole("radio", { name: "2100", exact: true }).check();
  await expect(active.locator(".projection-panel")).toHaveAttribute("data-phase", "connection-required");
  await expect(active.locator(".projection-panel").getByRole("alert"))
    .toContainText(/Connection required for selected data/i);
  await expect(active.locator(".projection-panel__outcome")).toHaveAttribute("data-outcome", "ProjectionAvailable");
  await setNetworkOffline(false);

  const requests = (await serverRequests()).slice(initialRequestCount);
  await testInfo.attach("offline-lifecycle-request-log", {
    body: Buffer.from(JSON.stringify({ browserRequests, staticResponses: requests }, null, 2)),
    contentType: "application/json",
  });
  expect(requests.length).toBeGreaterThan(0);
  const forbidden = requests.filter(({ path }) =>
    ["/assess", "/geocode", "/config"].includes(path) ||
    /candidate-v7|\.tar(?:\.|$)|__lifecycle/iu.test(path));
  expect(forbidden).toEqual([]);
  const forbiddenBrowserRequests = browserRequests.filter(({ path }) =>
    ["/assess", "/geocode", "/config"].includes(path) ||
    /candidate-v7|\.tar(?:\.|$)|__lifecycle/iu.test(path));
  expect(forbiddenBrowserRequests).toEqual([]);
});
