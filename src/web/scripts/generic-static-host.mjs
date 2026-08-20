import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { TextDecoder } from "node:util";

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

async function responseAt(request, origin, path, expectedStatus = 200, init = undefined) {
  const response = await request(new URL(path, origin), init);
  requireCondition(
    response.status === expectedStatus,
    `${init?.method ?? "GET"} ${path} returned ${response.status}; expected ${expectedStatus}`,
  );
  return response;
}

export async function validateGenericStaticHost(origin, dist, request = globalThis.fetch) {
  const root = await responseAt(request, origin, "/");
  requireCondition(root.headers.get("content-type")?.startsWith("text/html"), "/ is not HTML");
  requireCondition((await root.text()).includes('<div id="root"></div>'), "/ is not the built application shell");

  const architecture = await responseAt(request, origin, "/about/architecture/");
  requireCondition(
    architecture.headers.get("content-type")?.startsWith("text/html"),
    "/about/architecture/ is not HTML",
  );
  requireCondition(
    (await architecture.text()).includes('<div id="root"></div>'),
    "/about/architecture/ is not the built application shell",
  );

  const configResponse = await responseAt(request, origin, "/build-identity.json");
  requireCondition(
    configResponse.headers.get("content-type")?.startsWith("application/json"),
    "/build-identity.json is not JSON",
  );
  const config = await configResponse.json();
  requireCondition(
    typeof config.manifestPath === "string" && /^\/releases\/[^/]+\/manifest\.json$/u.test(config.manifestPath),
    "/build-identity.json does not name one release-scoped manifest",
  );
  const manifest = await responseAt(request, origin, config.manifestPath);
  requireCondition(manifest.headers.get("content-type")?.startsWith("application/json"), "release manifest is not JSON");
  const releaseManifest = await manifest.json();
  requireCondition(releaseManifest.dataReleaseId === config.dataReleaseId, "release manifest identity differs from config");
  const releaseRoot = config.manifestPath.slice(0, -"manifest.json".length);
  const releaseConfigs = releaseManifest.artifacts?.filter(({ path }) =>
    typeof path === "string" && /^config\/[A-Za-z0-9._-]+\.json$/u.test(path)
  );
  requireCondition(Array.isArray(releaseConfigs) && releaseConfigs.length > 0, "release manifest has no static config artifacts");
  for (const artifact of releaseConfigs) {
    requireCondition(artifact.mediaType === "application/json", `${artifact.path} manifest media type is not JSON`);
    const response = await responseAt(request, origin, `${releaseRoot}${artifact.path}`);
    requireCondition(response.headers.get("content-type")?.startsWith("application/json"), `${artifact.path} is not JSON`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    requireCondition(bytes.byteLength === artifact.byteSize, `${artifact.path} byte size differs from the release manifest`);
    requireCondition(createHash("sha256").update(bytes).digest("hex") === artifact.sha256, `${artifact.path} hash differs from the release manifest`);
    const document = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    requireCondition(document.dataReleaseId === config.dataReleaseId, `${artifact.path} release identity differs from config`);
    requireCondition(document.dataProvenanceClass === releaseManifest.dataProvenanceClass, `${artifact.path} provenance differs from the release manifest`);
    if (document.methodologyVersion !== undefined) {
      requireCondition(document.methodologyVersion === releaseManifest.methodologyVersion, `${artifact.path} methodology differs from the release manifest`);
    }
  }

  const buildReport = JSON.parse(readFileSync(resolve(dist, "build-report.json"), "utf8"));
  requireCondition(Array.isArray(buildReport.assets) && buildReport.assets.length > 0, "build report has no static assets");
  for (const asset of buildReport.assets) {
    const response = await responseAt(request, origin, `/${asset.path}`, 200, { headers: { "accept-encoding": "br" } });
    if (/^assets\/main-[^/]+\.js$/u.test(asset.path)) {
      requireCondition(response.headers.get("content-encoding") === "br", "initial JavaScript is not served from its Brotli sidecar");
    }
    requireCondition((await response.arrayBuffer()).byteLength === asset.bytes, `/${asset.path} byte size differs from the build report`);
  }

  for (const path of [
    "/__missing_static_file__",
    "/assess", "/geocode", "/config",
    "/v1/assess", "/v1/geocode", "/v1/config",
  ]) {
    await responseAt(request, origin, path, 404);
  }
  for (const path of [
    "/assess", "/geocode", "/config",
    "/v1/assess", "/v1/geocode", "/v1/config",
  ]) {
    await responseAt(request, origin, path, 404, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
  }
}
