import {
  buildBrowserSearchShards,
  validateBrowserSearchShards,
} from "../src/search/shards/browser-shards";

function usage(): never {
  throw new Error(
    "usage: build-settlement-search-shards.ts <build|validate> --projection <path> "
      + "--spatial-database <path> --spatial-receipt <path> --validation-work-dir <path> "
      + "--data-release-id <id> --output-dir <path>"
  );
}

function options(argv: string[]): {
  command: "build" | "validate";
  projection: string;
  spatialDatabase: string;
  spatialReceipt: string;
  validationWorkDirectory: string;
  dataReleaseId: string;
  output: string;
} {
  const command = argv.shift();
  if (command !== "build" && command !== "validate") usage();
  const values = new Map<string, string>();
  while (argv.length) {
    const name = argv.shift();
    const value = argv.shift();
    if (!name?.startsWith("--") || !value || value.startsWith("--") || values.has(name)) usage();
    values.set(name, value);
  }
  if (values.size !== 6 || !values.has("--projection") || !values.has("--spatial-database")
      || !values.has("--spatial-receipt") || !values.has("--validation-work-dir")
      || !values.has("--data-release-id")
      || !values.has("--output-dir")) usage();
  return {
    command,
    projection: values.get("--projection")!,
    spatialDatabase: values.get("--spatial-database")!,
    spatialReceipt: values.get("--spatial-receipt")!,
    validationWorkDirectory: values.get("--validation-work-dir")!,
    dataReleaseId: values.get("--data-release-id")!,
    output: values.get("--output-dir")!,
  };
}

try {
  const parsed = options(process.argv.slice(2));
  const result = parsed.command === "build"
    ? buildBrowserSearchShards(
      parsed.projection, parsed.spatialDatabase, parsed.spatialReceipt,
      parsed.validationWorkDirectory,
      parsed.dataReleaseId, parsed.output
    )
    : validateBrowserSearchShards(
      parsed.projection, parsed.spatialDatabase, parsed.spatialReceipt,
      parsed.validationWorkDirectory,
      parsed.dataReleaseId, parsed.output
    );
  process.stdout.write(`${JSON.stringify(result)}\n`);
} catch (error) {
  process.stderr.write(`${(error as Error).message}\n`);
  process.exitCode = 1;
}
