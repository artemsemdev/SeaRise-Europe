const SHA256_LINE = /^([0-9a-f]{64}) {2}([^\s].*)$/;

// `manifest.json` and `checksums.txt` are the only permitted exclusions.
// Hashing checksums.txt inside itself is directly self-referential. Hashing
// manifest.json in checksums.txt is mutually self-referential because the
// manifest records the byte identity of checksums.txt.
export const CHECKSUM_SELF_REFERENCE_EXCLUSIONS = Object.freeze([
  "manifest.json",
  "checksums.txt",
]);
const excludedPaths = new Set(CHECKSUM_SELF_REFERENCE_EXCLUSIONS);

export function parseChecksumText(text) {
  const identities = new Map();
  for (const [index, sourceLine] of text.split(/\r?\n/u).entries()) {
    const line = sourceLine.trim();
    if (line === "" || line.startsWith("#")) continue;
    const match = SHA256_LINE.exec(line);
    if (!match) throw new Error(`Invalid checksum line ${index + 1}`);
    const [, digest, path] = match;
    if (path.startsWith("#")) {
      throw new Error(`Checksum line ${index + 1} treats a comment as an artifact`);
    }
    if (identities.has(path)) throw new Error(`Duplicate checksum path: ${path}`);
    identities.set(path, digest);
  }
  return identities;
}

export function checksumInventory(manifest) {
  const identities = new Map();
  for (const artifact of manifest.artifacts) {
    if (excludedPaths.has(artifact.path)) continue;
    if (identities.has(artifact.path)) {
      throw new Error(`Duplicate manifest artifact path: ${artifact.path}`);
    }
    identities.set(artifact.path, artifact.sha256);
  }
  return identities;
}

export function assertChecksumInventory(manifest, checksumText) {
  const expected = checksumInventory(manifest);
  const actual = parseChecksumText(checksumText);
  for (const [path, digest] of expected) {
    if (!actual.has(path)) throw new Error(`Missing checksum path: ${path}`);
    if (actual.get(path) !== digest) throw new Error(`Stale checksum digest: ${path}`);
  }
  for (const path of actual.keys()) {
    if (!expected.has(path)) throw new Error(`Unexpected checksum path: ${path}`);
  }
  return actual;
}

export function canonicalChecksumText(manifest) {
  const lines = [...checksumInventory(manifest).entries()]
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([path, digest]) => `${digest}  ${path}`);
  return [
    "# Complete manifest artifact checksums; checksums.txt is excluded to avoid direct self-reference and manifest.json to avoid mutual manifest/checksums self-reference.",
    ...lines,
    "",
  ].join("\n");
}
