#!/usr/bin/env node
import { resolve } from "node:path";
import { startGenericStaticHost, stopGenericStaticHost, validateGenericStaticHost } from "./generic-static-host.mjs";

const dist = resolve(import.meta.dirname, "../dist");
const { child, origin } = await startGenericStaticHost({ dist });
try {
  await validateGenericStaticHost(origin, dist);
  console.log(`generic static-host validation passed at ${origin}`);
} finally {
  await stopGenericStaticHost(child);
}
