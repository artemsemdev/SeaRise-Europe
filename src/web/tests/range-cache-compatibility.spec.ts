import { expect, test } from "@playwright/test";
import manifest from "../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json" with { type: "json" };

const artifactIds = [
  "projection-ssp2-45-2050-cog",
  "projection-ssp2-45-2050-pmtiles",
] as const;
const artifacts = artifactIds.map((artifactId) => {
  const artifact = manifest.artifacts.find((candidate) => candidate.artifactId === artifactId);
  if (!artifact) throw new Error(`Committed range-cache fixture ${artifactId} is missing.`);
  return artifact;
});

const rangeStart = 65_536;
const rangeEnd = 65_599;
const sliceOffset = 8;
const sliceLength = 16;

for (const artifact of artifacts) test(`measures real 206 Cache API behavior for ${artifact.role}`, async ({
  browser,
  browserName,
  page,
}) => {
  await page.goto("/");
  const observation = await page.evaluate(async ({
    artifactPath,
    artifactSize,
    artifactSha256,
    rangeStart,
    rangeEnd,
    sliceOffset,
    sliceLength,
  }) => {
    const probeUrl = new URL(artifactPath, location.href).href;
    const cacheName = "searise-range-cache-compatibility-v1";
    const databaseName = "searise-range-cache-compatibility-v1";
    await caches.delete(cacheName);

    const rangeRequest = new Request(probeUrl, {
      headers: { Range: `bytes=${rangeStart}-${rangeEnd}` },
    });
    const rangedResponse = await fetch(rangeRequest);
    const rangedBytes = new Uint8Array(await rangedResponse.clone().arrayBuffer());
    const rangedHeaders = {
      acceptRanges: rangedResponse.headers.get("accept-ranges"),
      contentLength: rangedResponse.headers.get("content-length"),
      contentRange: rangedResponse.headers.get("content-range"),
      contentType: rangedResponse.headers.get("content-type"),
      etag: rangedResponse.headers.get("etag"),
    };

    const cache = await caches.open(cacheName);
    let direct206: {
      outcome: "stored" | "rejected";
      errorName: string | null;
      matchedStatus: number | null;
      matchedBytes: number | null;
    };
    try {
      await cache.put(rangeRequest, rangedResponse.clone());
      const matched = await cache.match(rangeRequest);
      direct206 = {
        outcome: "stored",
        errorName: null,
        matchedStatus: matched?.status ?? null,
        matchedBytes: matched ? (await matched.arrayBuffer()).byteLength : null,
      };
    } catch (error) {
      direct206 = {
        outcome: "rejected",
        errorName: error instanceof Error ? error.name : typeof error,
        matchedStatus: null,
        matchedBytes: null,
      };
    }

    await caches.delete(cacheName);
    const wholeCache = await caches.open(cacheName);
    const wholeRequest = new Request(probeUrl);
    const wholeResponse = await fetch(wholeRequest);
    await wholeCache.put(wholeRequest, wholeResponse.clone());
    const wholeMatch = await wholeCache.match(wholeRequest);
    const rangeAgainstWhole = await wholeCache.match(rangeRequest);

    const openDatabase = (): Promise<IDBDatabase> => new Promise((resolve, reject) => {
      const request = indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => request.result.createObjectStore("ranges", { keyPath: "key" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const database = await openDatabase();
    const putRange = (): Promise<void> => new Promise((resolve, reject) => {
      const transaction = database.transaction("ranges", "readwrite");
      transaction.objectStore("ranges").put({
        key: `${artifactSha256}:${rangeStart}:${rangeEnd}`,
        artifactSha256,
        artifactSize,
        start: rangeStart,
        end: rangeEnd,
        bytes: rangedBytes.buffer,
      });
      transaction.oncomplete = () => resolve();
      transaction.onabort = () => reject(transaction.error);
      transaction.onerror = () => reject(transaction.error);
    });
    const readRange = (): Promise<{
      artifactSha256: string;
      artifactSize: number;
      start: number;
      end: number;
      bytes: ArrayBuffer;
    }> => new Promise((resolve, reject) => {
      const request = database.transaction("ranges", "readonly")
        .objectStore("ranges")
        .get(`${artifactSha256}:${rangeStart}:${rangeEnd}`);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await putRange();
    const stored = await readRange();
    database.close();

    const storedBytes = new Uint8Array(stored.bytes);
    const selected = storedBytes.slice(sliceOffset, sliceOffset + sliceLength);
    const selectedStart = stored.start + sliceOffset;
    const selectedEnd = selectedStart + selected.byteLength - 1;
    const synthesized = new Response(selected, {
      status: 206,
      headers: {
        "Accept-Ranges": "bytes",
        "Content-Length": String(selected.byteLength),
        "Content-Range": `bytes ${selectedStart}-${selectedEnd}/${stored.artifactSize}`,
        "Content-Type": rangedHeaders.contentType ?? "application/octet-stream",
        ETag: `"sha256-${stored.artifactSha256}"`,
      },
    });
    const synthesizedBytes = new Uint8Array(await synthesized.clone().arrayBuffer());
    const deleteDatabase = (): Promise<void> => new Promise((resolve, reject) => {
      const request = indexedDB.deleteDatabase(databaseName);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("Compatibility database deletion was blocked."));
    });
    await caches.delete(cacheName);
    await deleteDatabase();

    return {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      originResponse: {
        status: rangedResponse.status,
        bytes: rangedBytes.byteLength,
        headers: rangedHeaders,
      },
      direct206,
      wholeResponseControl: {
        storedStatus: wholeMatch?.status ?? null,
        storedBytes: wholeMatch ? (await wholeMatch.clone().arrayBuffer()).byteLength : null,
        rangeRequestMatchedStatus: rangeAgainstWhole?.status ?? null,
        rangeRequestMatchedBytes: rangeAgainstWhole
          ? (await rangeAgainstWhole.arrayBuffer()).byteLength
          : null,
      },
      indexedDbRange: {
        storedBytes: storedBytes.byteLength,
        selectedBytes: selected.byteLength,
        selectedMatchesOrigin: selected.every(
          (value, index) => value === rangedBytes[sliceOffset + index],
        ),
        synthesizedStatus: synthesized.status,
        synthesizedBytes: synthesizedBytes.byteLength,
        synthesizedContentRange: synthesized.headers.get("content-range"),
        synthesizedContentLength: synthesized.headers.get("content-length"),
        synthesizedAcceptRanges: synthesized.headers.get("accept-ranges"),
        synthesizedEtag: synthesized.headers.get("etag"),
      },
    };
  }, {
    artifactPath: `/releases/${manifest.dataReleaseId}/${artifact.path}`,
    artifactSize: artifact.byteSize,
    artifactSha256: artifact.sha256,
    rangeStart,
    rangeEnd,
    sliceOffset,
    sliceLength,
  });

  console.log(`RANGE_CACHE_OBSERVATION ${JSON.stringify({
    browserName,
    browserVersion: browser.version(),
    ...observation,
  })}`);

  expect(observation.originResponse).toEqual({
    status: 206,
    bytes: rangeEnd - rangeStart + 1,
    headers: {
      acceptRanges: "bytes",
      contentLength: String(rangeEnd - rangeStart + 1),
      contentRange: `bytes ${rangeStart}-${rangeEnd}/${artifact.byteSize}`,
      contentType: artifact.mediaType,
      etag: `"sha256-${artifact.sha256}"`,
    },
  });
  expect(observation.direct206).toEqual({
    outcome: "rejected",
    errorName: "TypeError",
    matchedStatus: null,
    matchedBytes: null,
  });
  expect(observation.wholeResponseControl).toEqual({
    storedStatus: 200,
    storedBytes: artifact.byteSize,
    rangeRequestMatchedStatus: 200,
    rangeRequestMatchedBytes: artifact.byteSize,
  });
  expect(observation.indexedDbRange).toEqual({
    storedBytes: rangeEnd - rangeStart + 1,
    selectedBytes: sliceLength,
    selectedMatchesOrigin: true,
    synthesizedStatus: 206,
    synthesizedBytes: sliceLength,
    synthesizedContentRange: `bytes ${rangeStart + sliceOffset}-${rangeStart + sliceOffset + sliceLength - 1}/${artifact.byteSize}`,
    synthesizedContentLength: String(sliceLength),
    synthesizedAcceptRanges: "bytes",
    synthesizedEtag: `"sha256-${artifact.sha256}"`,
  });
});
