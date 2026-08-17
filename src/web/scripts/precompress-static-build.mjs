#!/usr/bin/env node
import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import { lstatSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";

const dist = resolve(import.meta.dirname, "../dist");
const compressible = new Set([".css", ".html", ".js", ".json", ".svg", ".xml"]);
let count = 0;

function visit(directory) {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    const metadata = lstatSync(path);
    if (metadata.isSymbolicLink()) throw new Error(`refusing to precompress symlink ${relative(dist, path)}`);
    if (metadata.isDirectory()) {
      visit(path);
      continue;
    }
    if (!metadata.isFile() || !compressible.has(extname(path)) || path.endsWith(".map")) continue;
    const source = readFileSync(path);
    const brotli = brotliCompressSync(source, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT,
      },
    });
    const gzip = gzipSync(source, { level: 9, mtime: 0 });
    if (brotli.length < source.length) writeFileSync(`${path}.br`, brotli);
    if (gzip.length < source.length) writeFileSync(`${path}.gz`, gzip);
    count += 1;
  }
}

visit(dist);
console.log(`precompressed ${count} static text assets`);
