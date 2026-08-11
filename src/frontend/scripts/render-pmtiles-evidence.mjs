#!/usr/bin/env node
/** Build deterministic, source-bound render evidence from an approved #110 PMTiles. */

import { createHash } from "node:crypto";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { VectorTile } from "@mapbox/vector-tile";
import { gunzipSync, zlibSync } from "fflate";
import Pbf from "pbf";
import { PMTiles, TileType } from "pmtiles";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const targetRelative = "layers/ssp5-85/2100.pmtiles";
const release = resolve(root, "contracts/release/v1/fixtures/release", releaseId);
const target = resolve(release, targetRelative);
const manifestPath = resolve(release, "manifest.json");
const sourceFixturePath = resolve(
  root,
  "src/pipeline/fixtures/ar6-regional-release/source-fixture.json.gz",
);
const sourceReceiptPath = resolve(
  root,
  "src/pipeline/fixtures/ar6-regional-release/source-fixture-receipt.json",
);
const finalGatePath = resolve(
  root,
  "src/pipeline/evidence/ar6-regional-release/owner-promotion/final-gate.json",
);
const reproducibilityPath = resolve(
  root,
  "src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311/reproducibility-report.json",
);
const outputDirectory = resolve(
  root,
  "src/pipeline/evidence/phase-1/pmtiles-render-v1",
);
const receiptPath = resolve(outputDirectory, "receipt.json");
const scriptPath = fileURLToPath(import.meta.url);
const packageLockPath = resolve(root, "src/frontend/package-lock.json");
const size = 512;

const samples = [
  { zoom: 0, x: 0, y: 0, property: "lower_mm" },
  { zoom: 3, x: 4, y: 2, property: "median_mm" },
  { zoom: 6, x: 35, y: 22, property: "upper_mm" },
];

const bins = [
  { id: "below-0-mm", maximum: -1, rgba: [49, 54, 149, 255] },
  { id: "0-249-mm", minimum: 0, maximum: 249, rgba: [69, 117, 180, 255] },
  { id: "250-499-mm", minimum: 250, maximum: 499, rgba: [145, 191, 219, 255] },
  { id: "500-749-mm", minimum: 500, maximum: 749, rgba: [244, 109, 67, 255] },
  { id: "750-mm-and-above", minimum: 750, rgba: [165, 0, 38, 255] },
];

function sha256(bytes) {
  return createHash("sha256")
    .update(bytes instanceof ArrayBuffer ? Buffer.from(bytes) : bytes)
    .digest("hex");
}

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function binFor(value) {
  const result = bins.find(
    (bin) =>
      (bin.minimum === undefined || value >= bin.minimum) &&
      (bin.maximum === undefined || value <= bin.maximum),
  );
  requireCondition(result, `no render bin covers ${value}`);
  return result;
}

function contains(rings, x, y) {
  let inside = false;
  for (const ring of rings) {
    for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
      const a = ring[index];
      const b = ring[previous];
      if ((a.y > y) !== (b.y > y) && x < ((b.x - a.x) * (y - a.y)) / (b.y - a.y) + a.x) {
        inside = !inside;
      }
    }
  }
  return inside;
}

function renderLayer(layer, property) {
  const rgba = Buffer.alloc(size * size * 4);
  const valuesById = new Map();
  const featureBinCounts = Object.fromEntries(bins.map((bin) => [bin.id, 0]));

  for (let index = 0; index < layer.length; index += 1) {
    const feature = layer.feature(index);
    const value = feature.properties[property];
    requireCondition(feature.type === 3, "MVT render feature is not a polygon");
    requireCondition(Number.isSafeInteger(feature.id), "MVT feature ID is not an exact integer");
    requireCondition(Number.isSafeInteger(value), `${property} is not an exact integer`);
    requireCondition(
      feature.properties.source_location_id === feature.id,
      "MVT source_location_id differs from the feature ID",
    );
    requireCondition(
      feature.properties.scenario === "ssp5-85" && feature.properties.horizon === 2100,
      "MVT scenario or horizon differs from the sample contract",
    );
    const previous = valuesById.get(feature.id);
    requireCondition(previous === undefined || previous === value, "MVT fragments disagree on value");
    if (previous === undefined) {
      valuesById.set(feature.id, value);
      featureBinCounts[binFor(value).id] += 1;
    }

    const rings = feature.loadGeometry();
    const xs = rings.flatMap((ring) => ring.map((point) => point.x));
    const ys = rings.flatMap((ring) => ring.map((point) => point.y));
    const minX = Math.max(0, Math.floor((Math.min(...xs) * size) / layer.extent));
    const maxX = Math.min(size - 1, Math.ceil((Math.max(...xs) * size) / layer.extent));
    const minY = Math.max(0, Math.floor((Math.min(...ys) * size) / layer.extent));
    const maxY = Math.min(size - 1, Math.ceil((Math.max(...ys) * size) / layer.extent));
    const color = binFor(value).rgba;
    for (let pixelY = minY; pixelY <= maxY; pixelY += 1) {
      const pointY = ((pixelY + 0.5) * layer.extent) / size;
      for (let pixelX = minX; pixelX <= maxX; pixelX += 1) {
        const pointX = ((pixelX + 0.5) * layer.extent) / size;
        if (!contains(rings, pointX, pointY)) continue;
        rgba.set(color, (pixelY * size + pixelX) * 4);
      }
    }
  }

  const pixelBinCounts = Object.fromEntries(bins.map((bin) => [bin.id, 0]));
  let transparentPixelCount = 0;
  for (let index = 0; index < rgba.length; index += 4) {
    if (rgba[index + 3] === 0) {
      transparentPixelCount += 1;
      continue;
    }
    const bin = bins.find(
      (candidate) => candidate.rgba.every((channel, offset) => rgba[index + offset] === channel),
    );
    requireCondition(bin, "render contains a colour outside the QA palette");
    pixelBinCounts[bin.id] += 1;
  }
  return { rgba, valuesById, featureBinCounts, pixelBinCounts, transparentPixelCount };
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const name = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([length, name, data, checksum]);
}

function encodePng(rgba) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header.set([8, 6, 0, 0, 0], 8);
  const scanlines = Buffer.alloc((size * 4 + 1) * size);
  for (let row = 0; row < size; row += 1) {
    const outputOffset = row * (size * 4 + 1);
    scanlines[outputOffset] = 0;
    rgba.copy(scanlines, outputOffset + 1, row * size * 4, (row + 1) * size * 4);
  }
  const compressed = Buffer.from(zlibSync(scanlines, { level: 9 }));
  return Buffer.concat([
    Buffer.from("89504e470d0a1a0a", "hex"),
    chunk("IHDR", header),
    chunk("IDAT", compressed),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function tileFor(longitude, latitude, zoom) {
  const scale = 2 ** zoom;
  return {
    worldX: ((longitude + 180) / 360) * scale,
    worldY: ((1 - Math.asinh(Math.tan((latitude * Math.PI) / 180)) / Math.PI) / 2) * scale,
  };
}

function findNodataProbe(source, sourceLayer, sample, valuesById, rgba) {
  const width = source.longitudes.length;
  for (let row = 0; row < source.latitudes.length; row += 1) {
    for (let column = 0; column < width; column += 1) {
      const sourceIndex = row * width + column;
      if (
        ![sourceLayer.lowerMm, sourceLayer.centralMm, sourceLayer.upperMm].every(
          (values) => values[sourceIndex] === -32768,
        )
      ) continue;
      const longitude = source.longitudes[column];
      const latitude = source.latitudes[row];
      const position = tileFor(longitude, latitude, sample.zoom);
      if (Math.floor(position.worldX) !== sample.x || Math.floor(position.worldY) !== sample.y) continue;
      const pixelX = Math.min(size - 1, Math.floor((position.worldX - sample.x) * size));
      const pixelY = Math.min(size - 1, Math.floor((position.worldY - sample.y) * size));
      const locationId = source.locationIds[sourceIndex];
      if (valuesById.has(locationId) || rgba[(pixelY * size + pixelX) * 4 + 3] !== 0) continue;
      return { sourceLocationId: locationId, longitude, latitude, pixelX, pixelY, alpha: 0 };
    }
  }
  throw new Error(`no transparent source-nodata probe found for z${sample.zoom}/${sample.x}/${sample.y}`);
}

async function buildEvidence() {
  const targetBytes = readFileSync(target);
  const manifestBytes = readFileSync(manifestPath);
  const manifest = JSON.parse(manifestBytes);
  const manifestArtifact = manifest.artifacts.find((artifact) => artifact.path === targetRelative);
  requireCondition(manifestArtifact?.sha256 === sha256(targetBytes), "manifest PMTiles hash differs");
  requireCondition(manifestArtifact?.role === "projection-visual-pmtiles", "manifest role differs");

  const finalGateBytes = readFileSync(finalGatePath);
  const finalGate = JSON.parse(finalGateBytes);
  requireCondition(
    finalGate.releaseId === "phase-0r-ar6-v1" &&
      finalGate.releaseDisposition === "approved" &&
      finalGate.phase1Unlocked === true,
    "the #110 owner gate is not approved",
  );
  const reproducibilityBytes = readFileSync(reproducibilityPath);
  const reproducibility = JSON.parse(reproducibilityBytes);
  requireCondition(
    finalGate.evidenceBindings.reproducibilityReportSha256 === sha256(reproducibilityBytes),
    "the owner gate does not bind the reviewed reproducibility report",
  );
  requireCondition(
    reproducibility.candidates.length >= 2 &&
      reproducibility.candidates.every(
      (candidate) => candidate.artifactHashes[targetRelative] === sha256(targetBytes),
      ),
    "the render input differs from a reviewed #110 candidate",
  );

  const sourceFixtureBytes = readFileSync(sourceFixturePath);
  const source = JSON.parse(Buffer.from(gunzipSync(sourceFixtureBytes)).toString("utf8"));
  const sourceReceiptBytes = readFileSync(sourceReceiptPath);
  const sourceReceipt = JSON.parse(sourceReceiptBytes);
  requireCondition(sourceReceipt.sha256 === sha256(sourceFixtureBytes), "source fixture receipt differs");
  const sourceLayer = source.layers.find(
    (layer) => layer.scenario === "ssp5-85" && layer.horizon === 2100,
  );
  requireCondition(sourceLayer, "source fixture lacks ssp5-85/2100");

  const packageLockBytes = readFileSync(packageLockPath);
  const packageLock = JSON.parse(packageLockBytes);
  const pmtiles = new PMTiles({
    getKey: () => targetRelative,
    getBytes: async (offset, length) => ({
      data: targetBytes.buffer.slice(
        targetBytes.byteOffset + offset,
        targetBytes.byteOffset + offset + length,
      ),
    }),
  });
  const header = await pmtiles.getHeader();
  const metadata = await pmtiles.getMetadata();
  requireCondition(
    header.tileType === TileType.Mvt &&
      header.minZoom === 0 &&
      header.maxZoom === 6 &&
      header.tileCompression === 2,
    "PMTiles header differs from the render contract",
  );
  requireCondition(
    metadata.searise?.scenario === "ssp5-85" &&
      metadata.searise?.horizon === 2100 &&
      metadata.searise?.visual_only === true &&
      metadata.searise?.scientific_lookup === "prohibited",
    "PMTiles metadata does not preserve the visual-only contract",
  );

  const rendered = [];
  const pngFiles = new Map();
  for (const sample of samples) {
    const tile = await pmtiles.getZxy(sample.zoom, sample.x, sample.y);
    requireCondition(tile, `PMTiles lacks z${sample.zoom}/${sample.x}/${sample.y}`);
    const vectorTile = new VectorTile(new Pbf(tile.data));
    const layer = vectorTile.layers.projection;
    requireCondition(layer, "MVT tile lacks the projection layer");
    const result = renderLayer(layer, sample.property);
    const nodataProbe = findNodataProbe(source, sourceLayer, sample, result.valuesById, result.rgba);
    const png = encodePng(result.rgba);
    const fileName = `z${sample.zoom}-${sample.x}-${sample.y}-${sample.property}.png`;
    pngFiles.set(fileName, png);
    rendered.push({
      zoom: sample.zoom,
      x: sample.x,
      y: sample.y,
      quantileProperty: sample.property,
      decodedTileSha256: sha256(tile.data),
      decodedFeatureFragmentCount: layer.length,
      uniqueSourceLocationCount: result.valuesById.size,
      featureBinCounts: result.featureBinCounts,
      pixelBinCounts: result.pixelBinCounts,
      transparentPixelCount: result.transparentPixelCount,
      nodataProbe,
      rawRgbaSha256: sha256(result.rgba),
      png: { path: fileName, byteSize: png.length, sha256: sha256(png) },
    });
  }

  const totalFeatureBins = Object.fromEntries(
    bins.map((bin) => [
      bin.id,
      rendered.reduce((sum, sample) => sum + sample.featureBinCounts[bin.id], 0),
    ]),
  );
  const totalPixelBins = Object.fromEntries(
    bins.map((bin) => [
      bin.id,
      rendered.reduce((sum, sample) => sum + sample.pixelBinCounts[bin.id], 0),
    ]),
  );
  requireCondition(Object.values(totalFeatureBins).every((count) => count > 0), "a QA value bin lacks features");
  requireCondition(Object.values(totalPixelBins).every((count) => count > 0), "a QA value bin lacks pixels");
  requireCondition(rendered.every((sample) => sample.transparentPixelCount > 0), "nodata transparency failed");

  return {
    receipt: {
      schemaVersion: 1,
      evidenceId: "phase-1-pmtiles-render-v1",
      issue: 51,
      status: "passed",
      purpose: "Deterministic QA renders; not a scientific lookup or production map-style contract.",
      input: {
        releaseFixtureId: releaseId,
        path: targetRelative,
        byteSize: targetBytes.length,
        sha256: sha256(targetBytes),
        manifestPath: relative(root, manifestPath),
        manifestSha256: sha256(manifestBytes),
        approvedPhase0rReleaseId: finalGate.releaseId,
        ownerGatePath: relative(root, finalGatePath),
        ownerGateSha256: sha256(finalGateBytes),
        reproducibilityReportPath: relative(root, reproducibilityPath),
        reproducibilityReportSha256: sha256(reproducibilityBytes),
        pmtilesHeader: {
          tileType: "mvt",
          tileCompression: "gzip",
          minimumZoom: header.minZoom,
          maximumZoom: header.maxZoom,
        },
        pmtilesMetadata: {
          scenario: metadata.searise.scenario,
          horizon: metadata.searise.horizon,
          visualOnly: metadata.searise.visual_only,
          scientificLookup: metadata.searise.scientific_lookup,
        },
      },
      sourceNodataOracle: {
        path: relative(root, sourceFixturePath),
        sha256: sha256(sourceFixtureBytes),
        receiptPath: relative(root, sourceReceiptPath),
        receiptSha256: sha256(sourceReceiptBytes),
        nodata: -32768,
      },
      renderer: {
        id: "projection-pmtiles-software-raster-v1",
        scriptPath: relative(root, scriptPath),
        scriptSha256: sha256(readFileSync(scriptPath)),
        width: size,
        height: size,
        sampling: "pixel-centre-even-odd",
        background: "transparent-rgba-0-0-0-0",
        pngEncoding: "rgba8-filter0-fflate-zlib9-no-interlace",
        pngCompressor: {
          name: "fflate",
          version: packageLock.packages["node_modules/fflate"].version,
        },
        palette: bins,
        packageLockPath: relative(root, packageLockPath),
        packageLockSha256: sha256(packageLockBytes),
        packages: {
          "@mapbox/vector-tile": packageLock.packages["node_modules/@mapbox/vector-tile"].version,
          fflate: packageLock.packages["node_modules/fflate"].version,
          pbf: packageLock.packages["node_modules/pbf"].version,
          pmtiles: packageLock.packages["node_modules/pmtiles"].version,
        },
      },
      assertions: {
        zooms: [0, 3, 6],
        quantileProperties: ["lower_mm", "median_mm", "upper_mm"],
        everySampleContainsTransparentNodataProbe: true,
        everyValueBinContainsFeatures: totalFeatureBins,
        everyValueBinContainsPixels: totalPixelBins,
      },
      samples: rendered,
    },
    pngFiles,
  };
}

const mode = process.argv[2];
requireCondition(mode === "--write" || mode === "--check", "use --write or --check");
const { receipt, pngFiles } = await buildEvidence();
const receiptBytes = Buffer.from(`${JSON.stringify(receipt, null, 2)}\n`);
if (mode === "--write") {
  mkdirSync(outputDirectory, { recursive: true });
  for (const [fileName, bytes] of pngFiles) writeFileSync(resolve(outputDirectory, fileName), bytes);
  writeFileSync(receiptPath, receiptBytes);
} else {
  requireCondition(readFileSync(receiptPath).equals(receiptBytes), "committed render receipt drifted");
  for (const [fileName, bytes] of pngFiles) {
    requireCondition(readFileSync(resolve(outputDirectory, fileName)).equals(bytes), `${fileName} drifted`);
  }
}
process.stdout.write(`${JSON.stringify({ mode, receipt: relative(root, receiptPath), samples: samples.length })}\n`);
