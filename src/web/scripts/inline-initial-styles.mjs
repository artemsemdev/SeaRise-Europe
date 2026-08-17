#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const dist = resolve(import.meta.dirname, "../dist");
const documents = ["index.html", "about/architecture/index.html"];
let expectedHref;

for (const document of documents) {
  const path = resolve(dist, document);
  const html = readFileSync(path, "utf8");
  const links = [...html.matchAll(/<link rel="stylesheet" crossorigin href="(\/assets\/[^"/]+\.css)">/gu)];
  if (links.length !== 1) throw new Error(`${document} must contain exactly one initial stylesheet link`);
  const href = links[0][1];
  if (expectedHref && href !== expectedHref) throw new Error("static routes do not share one initial stylesheet");
  expectedHref = href;
  const css = readFileSync(resolve(dist, href.slice(1)), "utf8");
  if (/<\/style/iu.test(css)) throw new Error("initial CSS cannot be safely embedded in HTML");
  writeFileSync(path, html.replace(links[0][0], `<style data-static-initial-css>${css}</style>`));
}

console.log(`inlined ${expectedHref} in ${documents.length} static routes`);
