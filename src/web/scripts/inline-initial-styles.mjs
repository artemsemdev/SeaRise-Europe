#!/usr/bin/env node
import { resolve } from "node:path";
import { inlineInitialStyles } from "./static-delivery-assets.mjs";

const dist = resolve(import.meta.dirname, "../dist");
const result = inlineInitialStyles(dist);
console.log(`inlined ${result.stylesheet} in ${result.documents} static routes`);
