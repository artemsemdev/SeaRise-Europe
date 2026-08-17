#!/usr/bin/env node
import { buildValidatedSearchShardSet, publishSearchShardSet, validatePublishedSearchShardSet } from "./search-shard-builder.mjs";

function usage() { throw new Error("usage: build-settlement-search-shards.mjs <build|validate> --projection PATH --projection-authority PATH --spatial-database PATH --spatial-receipt PATH --validation-work-dir PATH --data-release-id ID --output-dir PATH"); }
function parse(argv) {
  const command = argv.shift();
  if (!["build", "validate"].includes(command)) usage();
  const values = new Map();
  while (argv.length) { const name = argv.shift(); const value = argv.shift(); if (!name?.startsWith("--") || !value || value.startsWith("--") || values.has(name)) usage(); values.set(name, value); }
  const names = ["--projection", "--projection-authority", "--spatial-database", "--spatial-receipt", "--validation-work-dir", "--data-release-id", "--output-dir"];
  if (values.size !== names.length || names.some((name) => !values.has(name))) usage();
  return { command, projectionPath: values.get("--projection"), authorityPath: values.get("--projection-authority"), spatialDatabasePath: values.get("--spatial-database"), spatialReceiptPath: values.get("--spatial-receipt"), validationWorkDirectory: values.get("--validation-work-dir"), dataReleaseId: values.get("--data-release-id"), outputDirectory: values.get("--output-dir") };
}
try {
  const options = parse(process.argv.slice(2));
  const built = buildValidatedSearchShardSet(options);
  const result = options.command === "build" ? publishSearchShardSet(options.outputDirectory, built) : validatePublishedSearchShardSet(options.outputDirectory, built);
  process.stdout.write(`${JSON.stringify(result)}\n`);
} catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
