#!/usr/bin/env node
import { resolve } from "node:path";
import { validateGenericStaticHost } from "../../src/web/scripts/generic-static-host.mjs";
import { startGenericStaticHost, stopGenericStaticHost } from "./generic-static-host.mjs";

const dist = resolve(import.meta.dirname, "../../src/web/dist");
const { child, origin } = await startGenericStaticHost({ dist });
try {
  await validateGenericStaticHost(origin, dist);
  console.log(`generic static-host validation passed at ${origin}`);
} finally {
  await stopGenericStaticHost(child);
}
