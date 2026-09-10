import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import { readFileSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, resolve, sep } from "node:path";
import { brotliDecompressSync } from "node:zlib";

const CITY_LIMIT = 12;
const SHA256 = /^[a-f0-9]{64}$/u;

function normalize(value) {
  return value
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLowerCase()
    .trim()
    .replace(/\s+/gu, " ");
}

function confinedIndex(contextRoot, resource) {
  if (
    typeof resource?.file !== "string"
    || isAbsolute(resource.file)
    || !resource.file.endsWith(".json.br")
    || resource.file.split(/[\\/]/u).includes("..")
    || !Number.isSafeInteger(resource.byteSize)
    || resource.byteSize < 1
    || !SHA256.test(resource.sha256 ?? "")
  ) {
    throw new Error("The real-local place index identity is invalid.");
  }
  const root = realpathSync(contextRoot);
  const path = realpathSync(resolve(root, resource.file));
  if (!path.startsWith(`${root}${sep}`) || !statSync(path).isFile()) {
    throw new Error("The real-local place index escapes its data root.");
  }
  const bytes = readFileSync(path);
  if (
    bytes.length !== resource.byteSize
    || createHash("sha256").update(bytes).digest("hex") !== resource.sha256
  ) {
    throw new Error("The real-local place index differs from its manifest.");
  }
  return bytes;
}

function placeRecord(record) {
  if (!Array.isArray(record) || record.length !== 8 || !Array.isArray(record[7])) {
    throw new Error("The real-local place index contains an invalid record.");
  }
  const [id, name, countryCode, countryName, longitude, latitude, population, aliases] = record;
  if (
    !/^geonames:[1-9][0-9]*$/u.test(id)
    || typeof name !== "string"
    || name.trim() !== name
    || name.length === 0
    || !/^[A-Z]{2}$/u.test(countryCode)
    || typeof countryName !== "string"
    || countryName.trim() !== countryName
    || countryName.length === 0
    || !Number.isFinite(longitude)
    || longitude < -180
    || longitude > 180
    || !Number.isFinite(latitude)
    || latitude < -85
    || latitude > 85
    || !Number.isSafeInteger(population)
    || population < 0
    || aliases.length === 0
    || aliases.some((alias) => typeof alias !== "string" || normalize(alias).length === 0)
  ) {
    throw new Error("The real-local place index contains an invalid record.");
  }
  return Object.freeze({
    place: Object.freeze({
      id,
      name,
      countryCode,
      countryName,
      coordinates: Object.freeze([longitude, latitude]),
    }),
    population,
    aliases: Object.freeze(aliases.map(normalize)),
  });
}

export function loadRealLocalContext(contextRoot) {
  const root = realpathSync(contextRoot);
  const manifestPath = realpathSync(resolve(root, "manifest.json"));
  if (!manifestPath.startsWith(`${root}${sep}`) || !statSync(manifestPath).isFile()) {
    throw new Error("The real-local place manifest escapes its data root.");
  }
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (
    manifest.schemaVersion !== 1
    || !Number.isSafeInteger(manifest.totalPlaces)
    || manifest.totalPlaces < 1
  ) {
    throw new Error("The real-local place manifest is invalid.");
  }
  const document = JSON.parse(brotliDecompressSync(confinedIndex(root, manifest.index)));
  if (
    document.schemaVersion !== 1
    || document.totalPlaces !== manifest.totalPlaces
    || !Array.isArray(document.cities)
    || document.cities.length !== manifest.totalPlaces
  ) {
    throw new Error("The real-local place index is invalid.");
  }
  const entries = Object.freeze(document.cities.map(placeRecord));
  const byId = new Map(entries.map(({ place }) => [place.id, place]));
  if (byId.size !== entries.length) {
    throw new Error("The real-local place ids are not unique.");
  }
  return Object.freeze({ totalPlaces: manifest.totalPlaces, entries, byId });
}

export function searchRealLocalPlaces(context, rawQuery) {
  const query = normalize(rawQuery);
  if (query.length === 0) return Object.freeze([]);
  const matches = [];
  for (const entry of context.entries) {
    let tier = 3;
    for (const alias of entry.aliases) {
      if (alias === query) {
        tier = 0;
        break;
      }
      if (alias.startsWith(query)) tier = Math.min(tier, 1);
      else if (alias.includes(query)) tier = Math.min(tier, 2);
    }
    if (tier !== 3) matches.push({ ...entry, tier });
  }
  return Object.freeze(
    matches
      .sort(
        (left, right) => left.tier - right.tier
          || right.population - left.population
          || left.place.name.localeCompare(right.place.name, "en")
          || left.place.id.localeCompare(right.place.id),
      )
      .slice(0, CITY_LIMIT)
      .map(({ place }) => place),
  );
}

function json(response, status, body) {
  const bytes = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": bytes.length,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(bytes);
}

export function createRealLocalContextMiddleware(context) {
  return (request, response, next) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (!url.pathname.startsWith("/atlas-data/europe/")) {
      next();
      return;
    }
    if (request.method !== "GET") {
      response.writeHead(405, { Allow: "GET" }).end();
      return;
    }
    if (url.pathname === "/atlas-data/europe/search") {
      const keys = [...url.searchParams.keys()];
      const queries = url.searchParams.getAll("q");
      if (keys.length !== 1 || keys[0] !== "q" || queries.length !== 1 || queries[0].length > 160) {
        json(response, 400, { error: "Expected one search query of at most 160 characters." });
        return;
      }
      json(response, 200, {
        results: searchRealLocalPlaces(context, queries[0]),
        totalPlaces: context.totalPlaces,
      });
      return;
    }
    if (url.pathname === "/atlas-data/europe/place") {
      const keys = [...url.searchParams.keys()];
      const ids = url.searchParams.getAll("id");
      if (keys.length !== 1 || keys[0] !== "id" || ids.length !== 1) {
        json(response, 400, { error: "Expected one place id." });
        return;
      }
      const place = context.byId.get(ids[0]);
      if (!place) {
        json(response, 404, { error: "Place was not found." });
        return;
      }
      json(response, 200, place);
      return;
    }
    response.writeHead(404).end();
  };
}
