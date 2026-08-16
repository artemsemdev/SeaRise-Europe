import { readFileSync } from "node:fs";
import { extname, resolve } from "node:path";

const policyPath = resolve(import.meta.dirname, "../../../contracts/http-delivery/v1/policy.json");
export const RELEASE_DELIVERY_POLICY = Object.freeze(JSON.parse(readFileSync(policyPath, "utf8")));

const SHA256 = /^[0-9a-f]{64}$/u;
const visual = RELEASE_DELIVERY_POLICY.visualPmtiles;

function fail(message) {
  throw new TypeError(message);
}

function matchesIdentity(relativePath, artifact) {
  const rule = visual.roles[artifact.role];
  if (!rule) return false;
  if (rule.artifactId !== undefined) {
    return artifact.artifactId === rule.artifactId && relativePath === rule.path;
  }
  const artifactMatch = new RegExp(rule.artifactIdPattern, "u").exec(artifact.artifactId);
  const pathMatch = new RegExp(rule.pathPattern, "u").exec(relativePath);
  return artifactMatch !== null && pathMatch !== null &&
    artifactMatch[1] === pathMatch[1] && artifactMatch[2] === pathMatch[2];
}

export function releaseDeliveryPolicy(relativePath, artifact, actualByteSize) {
  if (typeof relativePath !== "string" || relativePath.length === 0 || relativePath.startsWith("/")) {
    fail("Release delivery path must be canonical and relative.");
  }
  const extension = extname(relativePath);
  const contentType = RELEASE_DELIVERY_POLICY.mediaTypes[extension] ?? "application/octet-stream";
  const isPmtiles = extension === ".pmtiles";
  if (isPmtiles && (!artifact || !matchesIdentity(relativePath, artifact))) {
    fail("PMTiles delivery requires an exact visual artifact role, identity, and path.");
  }
  if (artifact) {
    if (artifact.path !== relativePath || !SHA256.test(artifact.sha256)) {
      fail("Release delivery artifact identity is invalid.");
    }
    if (actualByteSize !== undefined && artifact.byteSize !== actualByteSize) {
      fail("Release delivery bytes do not match manifest byteSize.");
    }
    if (isPmtiles && artifact.mediaType !== visual.mediaType) {
      fail("PMTiles delivery media type does not match the role-specific contract.");
    }
  }
  return Object.freeze({
    cacheControl: isPmtiles ? visual.cacheControl : RELEASE_DELIVERY_POLICY.defaultCacheControl,
    contentType: isPmtiles ? visual.mediaType : contentType,
    etag: artifact ? `"sha256-${artifact.sha256}"` : null,
    networkOnly: isPmtiles,
  });
}

export function assertVisualPmtilesStatus(status) {
  if (!visual.statuses.includes(status)) fail(`HTTP ${status} is not a PMTiles delivery status.`);
}
