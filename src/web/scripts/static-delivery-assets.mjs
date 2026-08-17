import { lstatSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

const documents = ["index.html", "about/architecture/index.html"];
const initialFontPatterns = [
  /\/assets\/instrument-sans-latin-wght-normal-[A-Za-z0-9_-]+\.woff2/u,
  /\/assets\/instrument-serif-latin-400-normal-[A-Za-z0-9_-]+\.woff2/u,
];
const compressible = new Set([".css", ".html", ".js", ".json", ".svg", ".xml"]);

export function inlineInitialStyles(dist) {
  let expectedHref;
  for (const document of documents) {
    const path = resolve(dist, document);
    const html = readFileSync(path, "utf8");
    const links = [
      ...html.matchAll(/<link rel="stylesheet" crossorigin href="(\/assets\/[^"/]+\.css)">/gu),
    ];
    if (links.length !== 1) {
      throw new Error(`${document} must contain exactly one initial stylesheet link`);
    }
    const href = links[0][1];
    if (expectedHref && href !== expectedHref) {
      throw new Error("static routes do not share one initial stylesheet");
    }
    expectedHref = href;
    const css = readFileSync(resolve(dist, href.slice(1)), "utf8");
    if (/<\/style/iu.test(css)) throw new Error("initial CSS cannot be safely embedded in HTML");
    const initialFonts = initialFontPatterns.map((pattern) => css.match(pattern)?.[0]);
    if (
      initialFonts.some((font) => !font) ||
      new Set(initialFonts).size !== initialFontPatterns.length
    ) {
      throw new Error("initial CSS does not contain the exact Latin Flight fonts");
    }
    const preloads = initialFonts
      .map((font) => `<link rel="preload" href="${font}" as="font" type="font/woff2" crossorigin>`)
      .join("");
    writeFileSync(
      path,
      html.replace(links[0][0], `${preloads}<style data-static-initial-css>${css}</style>`),
    );
  }
  return { documents: documents.length, stylesheet: expectedHref };
}

export function precompressStaticBuild(dist) {
  const releaseRoot = resolve(dist, "releases");
  let count = 0;

  function visit(directory) {
    for (const name of readdirSync(directory)) {
      const path = join(directory, name);
      const metadata = lstatSync(path);
      if (metadata.isSymbolicLink()) {
        throw new Error(`refusing to precompress symlink ${relative(dist, path)}`);
      }
      if (metadata.isDirectory()) {
        if (path !== releaseRoot) visit(path);
        continue;
      }
      if (!metadata.isFile() || !compressible.has(extname(path)) || path.endsWith(".map")) {
        continue;
      }
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
  return { files: count };
}
