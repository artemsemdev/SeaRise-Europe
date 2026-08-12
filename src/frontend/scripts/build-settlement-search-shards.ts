import {
  buildBrowserSearchShards,
  validateBrowserSearchShards,
} from "../src/search/shards/browser-shards";

function usage(): never {
  throw new Error(
    "usage: build-settlement-search-shards.ts <build|validate> --projection <path> --output-dir <path>"
  );
}

function options(argv: string[]): { command: "build" | "validate"; projection: string; output: string } {
  const command = argv.shift();
  if (command !== "build" && command !== "validate") usage();
  const values = new Map<string, string>();
  while (argv.length) {
    const name = argv.shift();
    const value = argv.shift();
    if (!name?.startsWith("--") || !value || value.startsWith("--") || values.has(name)) usage();
    values.set(name, value);
  }
  if (values.size !== 2 || !values.has("--projection") || !values.has("--output-dir")) usage();
  return {
    command,
    projection: values.get("--projection")!,
    output: values.get("--output-dir")!,
  };
}

try {
  const parsed = options(process.argv.slice(2));
  const result = parsed.command === "build"
    ? buildBrowserSearchShards(parsed.projection, parsed.output)
    : validateBrowserSearchShards(parsed.projection, parsed.output);
  process.stdout.write(`${JSON.stringify(result)}\n`);
} catch (error) {
  process.stderr.write(`${(error as Error).message}\n`);
  process.exitCode = 1;
}
