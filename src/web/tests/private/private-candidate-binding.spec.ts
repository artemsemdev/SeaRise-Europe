import { expect, test } from "@playwright/test";
import { isForbiddenApplicationApiPath } from "../../src/test/application-api-boundary";

const expectedCsp =
  "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; manifest-src 'self'; media-src 'none'";

test("binds Candidate-v7 read-only through one private loopback origin", async ({ page }) => {
  test.setTimeout(60_000);
  const forbiddenRequests: string[] = [];
  const workerRequests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/service-worker.js") workerRequests.push(pathname);
    if (isForbiddenApplicationApiPath(pathname)) {
      forbiddenRequests.push(pathname);
    }
  });

  await page.goto("/");
  await expect(page.locator('meta[http-equiv="Content-Security-Policy"]')).toHaveAttribute(
    "content",
    expectedCsp,
  );
  await expect(page.getByText(/Private engineering release · local only/i)).toBeVisible();
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  expect(await page.evaluate(() => navigator.serviceWorker.getRegistrations().then((items) => items.length))).toBe(0);

  const initial = await page.evaluate(async () => {
    const response = await fetch("/__local-binding/status");
    return {
      status: response.status,
      cors: response.headers.get("access-control-allow-origin"),
      body: await response.json(),
    };
  });
  expect(initial).toMatchObject({
    status: 200,
    cors: new URL(page.url()).origin,
    body: {
      privateEngineeringOnly: true,
      verified: false,
      publicPromotionAuthorized: false,
      signatureAvailable: false,
      candidateSnapshot: { unchanged: true },
      sourceGridSnapshot: { unchanged: true },
      overlayPermissions: { directory: "0700", files: "0600" },
    },
  });

  const delivery = await page.evaluate(async (releaseId) => {
    const manifestResponse = await fetch(`/releases/${releaseId}/manifest.json`);
    const bindingManifest = await manifestResponse.json();
    const manifest = bindingManifest.releaseManifest;
    const root = `/releases/${manifest.dataReleaseId}/`;
    const analyses = manifest.datasets.map((dataset: { analysisArtifactId: string }) =>
      manifest.artifacts.find(
        (artifact: { artifactId: string }) => artifact.artifactId === dataset.analysisArtifactId,
      ),
    );
    const observations = [];
    for (const artifact of analyses) {
      const url = `${root}${artifact.path}`;
      const head = await fetch(url, { method: "HEAD" });
      const range = await fetch(url, { headers: { Range: "bytes=0-31" } });
      observations.push({
        path: artifact.path,
        headStatus: head.status,
        rangeStatus: range.status,
        contentRange: range.headers.get("content-range"),
        etag: range.headers.get("etag"),
        privateBinding: range.headers.get("x-searise-private-binding"),
        bytes: (await range.arrayBuffer()).byteLength,
      });
    }
    const probe = analyses[4];
    const probeUrl = `${root}${probe.path}`;
    const malformed = await fetch(probeUrl, { headers: { Range: "bytes=-16" } });
    const multiple = await fetch(probeUrl, { headers: { Range: "bytes=0-1,3-4" } });
    const unlisted = await fetch(`${root}package.json`);
    return {
      releaseId: manifest.dataReleaseId,
      bindingFlags: {
        privateEngineeringOnly: bindingManifest.privateEngineeringOnly,
        verified: bindingManifest.verified,
        publicPromotionAuthorized: bindingManifest.publicPromotionAuthorized,
      },
      provenance: manifest.dataProvenanceClass,
      disposition: manifest.releaseAuthority.releaseDisposition,
      cacheControl: manifest.publication.cacheControl,
      signature: manifest.contractArtifacts.baseReleaseSignature,
      baseReleaseIdentity: manifest.baseReleaseIdentity,
      browserDerivationIdentity: manifest.browserDerivationIdentity,
      automatedValidation: manifest.releaseAuthority.automatedValidation,
      datasets: manifest.datasets.map(
        (dataset: { scenario: string; horizon: number }) =>
          `${dataset.scenario}/${dataset.horizon}`,
      ),
      observations,
      malformed: malformed.status,
      multiple: multiple.status,
      unlisted: unlisted.status,
      manifestCors: manifestResponse.headers.get("access-control-allow-origin"),
    };
  }, initial.body.dataReleaseId);

  expect(delivery.provenance).toBe("real-source");
  expect(delivery.bindingFlags).toEqual({
    privateEngineeringOnly: true,
    verified: false,
    publicPromotionAuthorized: false,
  });
  expect(delivery.disposition).toBe("pending-owner");
  expect(delivery.automatedValidation).toBe("pending");
  expect(delivery.cacheControl).toBe("private, no-store");
  expect(delivery.signature).toBeNull();
  expect(delivery.baseReleaseIdentity).toMatchObject({
    identityScope: "private-phase-1-candidate",
    schemaVersion: "2.0.0",
  });
  expect(delivery.browserDerivationIdentity).toEqual({
    identityScope: "browser-overlay-derivation",
    executionIdentity: "not-recorded",
    receiptArtifactId: "browser-derivation-receipt",
    provenanceArtifactId: "browser-derivation-provenance",
  });
  expect(delivery.manifestCors).toBe(new URL(page.url()).origin);
  expect(delivery.datasets).toEqual([
    "ssp1-26/2030",
    "ssp1-26/2050",
    "ssp1-26/2100",
    "ssp2-45/2030",
    "ssp2-45/2050",
    "ssp2-45/2100",
    "ssp5-85/2030",
    "ssp5-85/2050",
    "ssp5-85/2100",
  ]);
  expect(delivery.observations).toHaveLength(9);
  for (const observation of delivery.observations) {
    expect(observation).toMatchObject({
      headStatus: 200,
      rangeStatus: 206,
      privateBinding: "true",
      bytes: 32,
    });
    expect(observation.contentRange).toMatch(/^bytes 0-31\/\d+$/);
    expect(observation.etag).toMatch(/^"sha256-[a-f0-9]{64}"$/);
  }
  expect(delivery).toMatchObject({ malformed: 416, multiple: 416, unlisted: 404 });

  const candidateRoot = process.env.SEARISE_LOCAL_CANDIDATE_ROOT!;
  const sourceGrid = process.env.SEARISE_LOCAL_SOURCE_GRID!;
  const forbiddenFilesystemRoutes = [
    `/@fs/${candidateRoot}/manifest.json`,
    `/@fs/${encodeURIComponent(`${candidateRoot}/manifest.json`)}`,
    `/@fs/%2e%2e/${encodeURIComponent(`${candidateRoot}/manifest.json`)}`,
    `/%40fs/${encodeURIComponent(sourceGrid)}`,
    `/${candidateRoot}/manifest.json`,
    `/${sourceGrid}`,
  ];
  const filesystemProbes = await page.evaluate(async (routes) =>
    Promise.all(
      routes.map(async (route) => {
        const probe = new URL(location.origin);
        probe.pathname = route;
        const response = await fetch(probe);
        return { status: response.status, byteLength: (await response.arrayBuffer()).byteLength };
      }),
    ), forbiddenFilesystemRoutes);
  expect(filesystemProbes).toEqual(
    forbiddenFilesystemRoutes.map(() => ({ status: 404, byteLength: 0 })),
  );

  await page.waitForFunction(() => Boolean(window.__SEARISE_PRIVATE_CANDIDATE_VALIDATION__));
  const scientific = await page.evaluate(() =>
    window.__SEARISE_PRIVATE_CANDIDATE_VALIDATION__!.run(),
  );
  expect(scientific.lookups).toHaveLength(9);
  expect(
    scientific.lookups.map((result) => ({
      state: result.resultState,
      scenario: result.scenario,
      horizon: result.horizon,
      source: "source" in result ? result.source : null,
      quantiles:
        result.resultState === "ProjectionAvailable"
          ? [result.lowerMillimetres, result.medianMillimetres, result.upperMillimetres]
          : null,
    })),
  ).toEqual([
    ["ssp1-26", 2030, [66, 120, 180]],
    ["ssp1-26", 2050, [135, 229, 337]],
    ["ssp1-26", 2100, [277, 478, 719]],
    ["ssp2-45", 2030, [64, 122, 184]],
    ["ssp2-45", 2050, [156, 247, 351]],
    ["ssp2-45", 2100, [408, 600, 851]],
    ["ssp5-85", 2030, [68, 122, 179]],
    ["ssp5-85", 2050, [170, 269, 382]],
    ["ssp5-85", 2100, [570, 808, 1123]],
  ].map(([scenario, horizon, quantiles]) => ({
    state: "ProjectionAvailable",
    scenario,
    horizon,
    source: {
      locationId: 1_003_800_040,
      latitude: 52,
      longitude: 4,
      distanceKilometres: 33.792469,
    },
    quantiles,
  })));
  expect(new Set(scientific.outcomes)).toEqual(
    new Set(["ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography"]),
  );
  expect(scientific.technicalFailure).toEqual({ kind: "technical-error", code: "FetchFailed" });

  const finalStatus = await page.evaluate(async () =>
    fetch("/__local-binding/status").then((response) => response.json()),
  );
  expect(finalStatus.candidateSnapshot).toEqual({
    initialSha256: initial.body.candidateSnapshot.initialSha256,
    currentSha256: initial.body.candidateSnapshot.initialSha256,
    unchanged: true,
  });
  expect(finalStatus.sourceGridSnapshot).toEqual({
    initialSha256: initial.body.sourceGridSnapshot.initialSha256,
    currentSha256: initial.body.sourceGridSnapshot.initialSha256,
    unchanged: true,
  });
  expect(forbiddenRequests).toEqual([]);
  expect(workerRequests).toEqual([]);
});
