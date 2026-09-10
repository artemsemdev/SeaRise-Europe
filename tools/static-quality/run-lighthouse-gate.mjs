#!/usr/bin/env node
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";
import { launch } from "chrome-launcher";
import lighthouse from "lighthouse";
import { validateGenericStaticHost } from "../../src/web/scripts/generic-static-host.mjs";
import { evaluateLighthouseBudget } from "../../src/web/scripts/lighthouse-budget.mjs";
import { startGenericStaticHost, stopGenericStaticHost } from "./generic-static-host.mjs";

const categories = ["performance", "accessibility", "best-practices", "seo"];
const dist = resolve(import.meta.dirname, "../../src/web/dist");
const evidenceDirectory = resolve(import.meta.dirname, "../../src/web/test-results/lighthouse");
const { child, origin } = await startGenericStaticHost({ dist });
try {
  await validateGenericStaticHost(origin, dist);
  rmSync(evidenceDirectory, { force: true, recursive: true });
  mkdirSync(evidenceDirectory, { recursive: true });
  const chromeOptions = {
    chromePath: chromium.executablePath(),
    chromeFlags: ["--headless", "--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    logLevel: "silent",
  };
  // Prove render health in a separate browser. Loading the app in an audit
  // browser would warm its shader/compiler caches even after a page reset.
  const preflightChrome = await launch(chromeOptions);
  try {
    const browser = await chromium.connectOverCDP(`http://127.0.0.1:${preflightChrome.port}`);
    const page = await browser.contexts()[0].newPage();
    await page.goto(`${origin}/?qa=map`);
    await page.waitForFunction(() => {
      const map = document.querySelector(".atlas-map");
      const mapApi = window.__SEARISE_ATLAS_MAP__;
      const count = map?.getAttribute("data-valid-pixels");
      return map?.querySelector("canvas") && count !== null && count !== ""
        && mapApi?.isStyleLoaded() && !mapApi.isMoving()
        && mapApi.queryRenderedFeatures().length > 0
        && document.querySelector(".atlas-fixture-label strong")?.textContent === "Illustrative fixture"
        && !document.querySelector('[role="alert"]');
    }, undefined, { timeout: 30_000 });
  } finally {
    await preflightChrome.kill();
  }
  const runs = [];
  for (let index = 0; index < 3; index += 1) {
    const chrome = await launch(chromeOptions);
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
      writeFileSync(resolve(evidenceDirectory, `report-run-${index + 1}.json`), result.report);
      const renderFailures = result.lhr.audits["errors-in-console"]?.details?.items
        ?.filter((item) => item.source === "console.error") ?? [];
      if (result.lhr.runtimeError) renderFailures.push(result.lhr.runtimeError);
      if (renderFailures.length) throw new Error(`Atlas audit logged application errors: ${renderFailures.map((item) => item.description ?? item.message ?? item.code).join("; ")}`);
      const scores = Object.fromEntries(categories.map((id) => [id, result.lhr.categories[id]?.score ?? 0]));
      runs.push({ run: index + 1, scores, renderErrors: renderFailures });
      console.log(`Lighthouse mobile run ${index + 1}: ${categories.map((id) => `${id}=${Math.round(scores[id] * 100)}`).join(", ")}`);
    } finally {
      await chrome.kill();
    }
  }
  const policy = JSON.parse(readFileSync(new URL("./atlas-local-performance-waiver.json", import.meta.url), "utf8"));
  const edition = readFileSync(resolve(dist, "index.html"), "utf8")
    .match(/<meta name="searise-atlas-edition" content="([^"]+)"/u)?.[1];
  const { releaseDisposition } = JSON.parse(readFileSync(resolve(dist, "build-identity.json"), "utf8"));
  const budget = evaluateLighthouseBudget({ runs, policy, edition, releaseDisposition });
  const { medianScores } = budget;
  writeFileSync(resolve(evidenceDirectory, "summary.json"), `${JSON.stringify({
    url: origin,
    profile: "mobile-simulated-three-run-median",
    runs,
    medianScores,
    budget,
  }, null, 2)}\n`);
  console.log(`Lighthouse mobile median: ${categories.map((id) => `${id}=${Math.round(medianScores[id] * 100)}`).join(", ")}`);
  if (budget.warning) console.warn(`::warning::${budget.warning}`);
  if (!budget.accepted) throw new Error(`Lighthouse raw budgets failed: ${budget.failedBudgets.join(", ")}`);
} finally {
  await stopGenericStaticHost(child);
}
