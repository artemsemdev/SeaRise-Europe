#!/usr/bin/env node
import { resolve } from "node:path";
import { precompressStaticBuild } from "./static-delivery-assets.mjs";

const dist = resolve(import.meta.dirname, "../dist");
const result = precompressStaticBuild(dist);
console.log(`precompressed ${result.files} static text assets`);
