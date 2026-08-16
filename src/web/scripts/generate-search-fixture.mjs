import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const releaseRoot = resolve(
  import.meta.dirname,
  "../../../contracts/release/v1/fixtures/release",
  releaseId,
);
const check = process.argv.includes("--check");
const manifestPath = resolve(releaseRoot, "manifest.json");
const checksumsPath = resolve(releaseRoot, "checksums.txt");

const records = Object.freeze([
  { placeId: "synthetic:1", displayName: "Málaga", searchNames: ["Malaga City"], countryCode: "ES", admin1Name: "Andalucía", population: 578460, featureCode: "PPLA", distanceToCoastMeters: 50, isCoastal: true, latitude: 36.7213, longitude: -4.4214, memberships: ["europe-core", "europe-coastal"] },
  { placeId: "synthetic:2", displayName: "Αθήνα", searchNames: ["Athens", "Athina"], countryCode: "GR", admin1Name: "Attica", population: 637798, featureCode: "PPLC", distanceToCoastMeters: 7000, isCoastal: true, latitude: 37.9838, longitude: 23.7275, memberships: ["europe-core"] },
  { placeId: "synthetic:3", displayName: "Springfield", searchNames: [], countryCode: "AA", admin1Name: "North", population: 1000, featureCode: "PPL", distanceToCoastMeters: 50000, isCoastal: false, latitude: 50, longitude: 10, memberships: ["europe-core"] },
  { placeId: "synthetic:4", displayName: "Springfield", searchNames: [], countryCode: "BB", admin1Name: "South", population: 500, featureCode: "PPL", distanceToCoastMeters: 100, isCoastal: true, latitude: 50.1, longitude: 10.1, memberships: ["europe-coastal"] },
  { placeId: "synthetic:5", displayName: "Islet Village", searchNames: [], countryCode: "CC", admin1Name: "Island", population: 0, featureCode: "PPL", distanceToCoastMeters: 0, isCoastal: true, latitude: 54, longitude: -10, memberships: ["europe-coastal"] },
  { placeId: "synthetic:6", displayName: "Border City", searchNames: [], countryCode: "TR", admin1Name: "Boundary", population: 2000, featureCode: "PPL", distanceToCoastMeters: 10000, isCoastal: false, latitude: 41, longitude: 29, memberships: ["europe-core"] },
]);

function normalize(value) {
  return value.normalize("NFKD").replace(/\p{M}+/gu, "").toLowerCase().trim().replace(/\s+/g, " ");
}

function shard(shardId) {
  const selected = records.filter(({ memberships }) => memberships.includes(shardId));
  const postings = new Map();
  selected.forEach((record, index) => {
    for (const name of new Set([record.displayName, ...record.searchNames].map(normalize))) {
      postings.set(name, [...(postings.get(name) ?? []), index + 1]);
    }
  });
  const envelope = {
    formatVersion: "search-evaluation-index-v1",
    engine: { engineId: "searise-codepoint-trie", packageVersion: "1.0.0", serializationVersion: "codepoint-trie-json-v1" },
    binding: { documentCount: selected.length, evaluationId: "browser-search-shard-v2", shardId },
    payload: { serializationVersion: 1, entries: [...postings].sort(([left], [right]) => left.localeCompare(right)) },
  };
  return `${JSON.stringify({
    artifactType: "settlement-browser-search-shard",
    contentEncoding: "identity",
    dataProvenanceClass: "synthetic-fixture",
    dataReleaseId: releaseId,
    formatVersion: "settlement-browser-search-shard-v2",
    indexBase64: Buffer.from(JSON.stringify(envelope)).toString("base64"),
    recordCount: selected.length,
    records: selected.map((record, index) => ({
      ordinal: index + 1,
      placeId: record.placeId,
      displayName: record.displayName,
      searchNames: record.searchNames,
      countryCode: record.countryCode,
      admin1Name: record.admin1Name,
      population: record.population,
      featureCode: record.featureCode,
      distanceToCoastMeters: record.distanceToCoastMeters,
      isCoastal: record.isCoastal,
      latitude: record.latitude,
      longitude: record.longitude,
    })),
    shardId,
  })}\n`;
}

const generated = [];
for (const shardId of ["europe-core", "europe-coastal"]) {
  const path = resolve(releaseRoot, `search/${shardId}.fixture.json`);
  const value = shard(shardId);
  if (check) {
    if (readFileSync(path, "utf8") !== value) throw new Error(`${shardId} synthetic search fixture is stale`);
  } else {
    writeFileSync(path, value);
  }
  const bytes = Buffer.from(value);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  generated.push({ shardId, bytes: bytes.length, sha256, path: `search/${shardId}.fixture.json` });
  console.log(`${shardId} ${bytes.length} ${sha256}`);
}

const checksumLines = readFileSync(checksumsPath, "utf8").trimEnd().split("\n");
const checksumHeader = checksumLines.shift();
const retainedChecksums = checksumLines.filter((line) => !generated.some(({ path }) => line.endsWith(`  ${path}`)));
const nextChecksums = `${checksumHeader}\n${[
  ...retainedChecksums,
  ...generated.map(({ path, sha256 }) => `${sha256}  ${path}`),
].sort((left, right) => left.slice(66).localeCompare(right.slice(66))).join("\n")}\n`;
if (check) {
  if (readFileSync(checksumsPath, "utf8") !== nextChecksums) throw new Error("synthetic release checksums are stale");
} else {
  writeFileSync(checksumsPath, nextChecksums);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const newArtifacts = generated.map(({ shardId, bytes, sha256, path }) => ({
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/artifact.schema.json",
  artifactId: `settlements-${shardId.replace("europe-", "europe-")}`,
  byteSize: bytes,
  dataProvenanceClass: "synthetic-fixture",
  dataReleaseId: releaseId,
  immutable: true,
  lineage: [{ path: "search/settlements.parquet", sha256: "cdb76a7956b5e627bbb2cfb18a4369ed955b703817ba87b58afa11240357ccee" }],
  mediaType: "application/vnd.searise.search-index+json",
  path,
  rights: { attributionIds: ["geonames-fixture"], redistribution: "allowed" },
  role: "settlement-search-index",
  schemaVersion: "1.0.0",
  scientificUse: "not-applicable",
  sha256,
  spatialBounds: null,
}));
const generatedIds = new Set(newArtifacts.map(({ artifactId }) => artifactId));
const artifacts = manifest.artifacts.filter(({ artifactId }) => !generatedIds.has(artifactId));
const searchRecordIndex = artifacts.findIndex(({ artifactId }) => artifactId === "search-records");
artifacts.splice(searchRecordIndex + 1, 0, ...newArtifacts);
manifest.artifacts = artifacts;
const checksumArtifact = manifest.artifacts.find(({ artifactId }) => artifactId === "checksums");
checksumArtifact.byteSize = Buffer.byteLength(nextChecksums);
checksumArtifact.sha256 = createHash("sha256").update(nextChecksums).digest("hex");
const nextManifest = `${JSON.stringify(manifest)}\n`;
if (check) {
  if (readFileSync(manifestPath, "utf8") !== nextManifest) throw new Error("synthetic release manifest search bindings are stale");
} else {
  writeFileSync(manifestPath, nextManifest);
}
