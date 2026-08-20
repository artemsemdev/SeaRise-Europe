import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const buildIdentity = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "../dist/build-identity.json"), "utf8"),
) as Readonly<{ appBuildId: string; dataReleaseId: string }>;
const pair = Object.freeze({
  contractVersion: 1,
  appBuildId: buildIdentity.appBuildId,
  dataReleaseId: buildIdentity.dataReleaseId,
});

type StoredLease = Readonly<{
  leaseId: string;
  pairKey: string;
  sourceClientId: string;
  expiresAtEpochMs: number;
}>;

async function storedLeases(page: import("@playwright/test").Page): Promise<readonly StoredLease[]> {
  return page.evaluate(async () => {
    const known = await indexedDB.databases();
    if (!known.some(({ name }) => name === "searise-offline:v1")) return [];
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("searise-offline:v1");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      if (!database.objectStoreNames.contains("leases")) return [];
      return await new Promise<StoredLease[]>((resolve, reject) => {
        const transaction = database.transaction("leases", "readonly");
        const request = transaction.objectStore("leases").getAll();
        request.onsuccess = () => resolve(request.result as StoredLease[]);
        request.onerror = () => reject(request.error);
      });
    } finally {
      database.close();
    }
  });
}

async function clientCensus(page: import("@playwright/test").Page) {
  return page.evaluate(async (targetPair) => {
    const registration = await navigator.serviceWorker.ready;
    if (!registration.active) throw new Error("The exact service worker is not active.");
    const channel = new MessageChannel();
    return new Promise<unknown>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error("Client census timed out.")), 10_000);
      channel.port1.onmessage = ({ data }) => {
        window.clearTimeout(timeout);
        channel.port1.close();
        resolve(data);
      };
      registration.active!.postMessage({
        protocol: "searise-offline-worker-v1",
        type: "request-client-census",
        messageToken: "e2e-client-census",
        targetPair,
      }, [channel.port2]);
    });
  }, pair) as Promise<Readonly<{
    type: string;
    targetPair: typeof pair;
    observations: readonly Readonly<{ clientId: string; state: string }>[];
  }>>;
}

test("source-bound leases and worker census isolate concurrent tabs", async ({ context, page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium");

  await page.goto("/");
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  await expect.poll(() => storedLeases(page)).toHaveLength(1);

  const second = await context.newPage();
  await second.goto("/");
  await expect(second.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  await expect.poll(() => storedLeases(second)).toHaveLength(2);

  const concurrent = await storedLeases(second);
  expect(new Set(concurrent.map(({ leaseId }) => leaseId)).size).toBe(2);
  expect(new Set(concurrent.map(({ sourceClientId }) => sourceClientId)).size).toBe(2);
  expect(concurrent.every(({ sourceClientId }) => sourceClientId.length > 0)).toBe(true);

  const census = await clientCensus(second);
  expect(census.type).toBe("client-census");
  expect(census.targetPair).toEqual(pair);
  expect(census.observations).toHaveLength(2);
  expect(census.observations.every(({ state }) => state === "active")).toBe(true);
  expect(new Set(census.observations.map(({ clientId }) => clientId))).toEqual(
    new Set(concurrent.map(({ sourceClientId }) => sourceClientId)),
  );

  await page.close();
  await expect.poll(() => storedLeases(second)).toHaveLength(1);
  const remaining = await storedLeases(second);
  expect(remaining[0]?.sourceClientId).toBe(
    (await clientCensus(second)).observations[0]?.clientId,
  );
});
