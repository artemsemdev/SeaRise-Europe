#!/usr/bin/env node
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { launch } from "chrome-launcher";
import lighthouse from "lighthouse";
import { chromium } from "@playwright/test";
import { startGenericStaticHost, stopGenericStaticHost, validateGenericStaticHost } from "./generic-static-host.mjs";

const categories = ["performance", "accessibility", "best-practices", "seo"];
const dist = resolve(import.meta.dirname, "../dist");
const evidenceDirectory = resolve(import.meta.dirname, "../test-results/lighthouse");
const { child, origin } = await startGenericStaticHost({ dist, port: 4175 });
let chrome;
try {
  await validateGenericStaticHost(origin, dist);
  chrome = await launch({
    chromePath: chromium.executablePath(),
    chromeFlags: ["--headless", "--no-sandbox", "--disable-gpu"],
    logLevel: "silent",
  });
  const result = await lighthouse(origin, {
    port: chrome.port,
    output: "json",
    logLevel: "error",
    onlyCategories: categories,
    formFactor: "mobile",
    screenEmulation: { mobile: true, width: 412, height: 823, deviceScaleFactor: 2.625, disabled: false },
    throttlingMethod: "simulate",
  });
  if (!result) throw new Error("Lighthouse returned no result");
  const scores = Object.fromEntries(categories.map((id) => [id, Math.round((result.lhr.categories[id]?.score ?? 0) * 100)]));
  mkdirSync(evidenceDirectory, { recursive: true });
  writeFileSync(resolve(evidenceDirectory, "report.json"), result.report);
  writeFileSync(resolve(evidenceDirectory, "summary.json"), `${JSON.stringify({ url: origin, profile: "mobile-simulated", scores }, null, 2)}\n`);
  console.log(`Lighthouse mobile scores: ${categories.map((id) => `${id}=${scores[id]}`).join(", ")}`);
  const failures = categories.filter((id) => scores[id] < 90);
  if (failures.length > 0) throw new Error(`Lighthouse categories below 90: ${failures.join(", ")}`);
} finally {
  if (chrome) await chrome.kill();
  await stopGenericStaticHost(child);
}
