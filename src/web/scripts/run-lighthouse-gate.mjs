#!/usr/bin/env node
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { launch } from "chrome-launcher";
import lighthouse from "lighthouse";
import { chromium } from "@playwright/test";
import { startGenericStaticHost, stopGenericStaticHost, validateGenericStaticHost } from "./generic-static-host.mjs";

const categories = ["performance", "accessibility", "best-practices", "seo"];
const dist = resolve(import.meta.dirname, "../dist");
const evidenceDirectory = resolve(import.meta.dirname, "../test-results/lighthouse");
const { child, origin } = await startGenericStaticHost({ dist, port: 4175 });
try {
  await validateGenericStaticHost(origin, dist);
  rmSync(evidenceDirectory, { force: true, recursive: true });
  mkdirSync(evidenceDirectory, { recursive: true });
  const runs = [];
  for (let index = 0; index < 3; index += 1) {
    const chrome = await launch({
      chromePath: chromium.executablePath(),
      chromeFlags: ["--headless", "--no-sandbox", "--disable-gpu"],
      logLevel: "silent",
    });
    try {
      const result = await lighthouse(origin, {
        port: chrome.port,
        output: "json",
        logLevel: "error",
        onlyCategories: categories,
        formFactor: "mobile",
        screenEmulation: { mobile: true, width: 412, height: 823, deviceScaleFactor: 2.625, disabled: false },
        throttlingMethod: "simulate",
      });
      if (!result) throw new Error(`Lighthouse run ${index + 1} returned no result`);
      const scores = Object.fromEntries(categories.map((id) => [id, result.lhr.categories[id]?.score ?? 0]));
      runs.push({ run: index + 1, scores });
      writeFileSync(resolve(evidenceDirectory, `report-run-${index + 1}.json`), result.report);
      console.log(`Lighthouse mobile run ${index + 1}: ${categories.map((id) => `${id}=${Math.round(scores[id] * 100)}`).join(", ")}`);
    } finally {
      await chrome.kill();
    }
  }
  const medianScores = Object.fromEntries(categories.map((id) => {
    const ordered = runs.map(({ scores }) => scores[id]).sort((left, right) => left - right);
    return [id, ordered[1]];
  }));
  writeFileSync(resolve(evidenceDirectory, "summary.json"), `${JSON.stringify({
    url: origin,
    profile: "mobile-simulated-three-run-median",
    runs,
    medianScores,
  }, null, 2)}\n`);
  console.log(`Lighthouse mobile median: ${categories.map((id) => `${id}=${Math.round(medianScores[id] * 100)}`).join(", ")}`);
  const medianFailures = categories.filter((id) => medianScores[id] < 0.9);
  const runFailures = runs.flatMap(({ run, scores }) =>
    categories.filter((id) => scores[id] < 0.9).map((id) => `run ${run} ${id}`)
  );
  if (medianFailures.length > 0 || runFailures.length > 0) {
    throw new Error(`Lighthouse raw scores below 0.90: ${[...medianFailures.map((id) => `median ${id}`), ...runFailures].join(", ")}`);
  }
} finally {
  await stopGenericStaticHost(child);
}
