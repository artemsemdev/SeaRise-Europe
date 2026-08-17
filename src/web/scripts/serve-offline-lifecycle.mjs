import { once } from "node:events";
import { prepareOfflineLifecycleFixtures } from "./offline-lifecycle-fixtures.mjs";
import { createOfflineLifecycleServer } from "./offline-lifecycle-server.mjs";

const host = "127.0.0.1";
const port = Number(process.env.SEARISE_LIFECYCLE_PORT ?? "8093");
const controlToken = process.env.SEARISE_LIFECYCLE_CONTROL_TOKEN;
if (!Number.isSafeInteger(port) || port < 1024 || port > 65_535) throw new Error("Lifecycle server port is invalid.");
if (typeof controlToken !== "string" || controlToken.length < 32 || controlToken.length > 256) {
  throw new Error("SEARISE_LIFECYCLE_CONTROL_TOKEN must contain 32-256 characters.");
}

const fixtures = prepareOfflineLifecycleFixtures();
const { server } = createOfflineLifecycleServer({ fixtures, controlToken });
let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  server.close();
  await once(server, "close").catch(() => undefined);
  fixtures.cleanup();
}
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => { void close().then(() => process.exit(0)); });
}
process.once("uncaughtException", (error) => { void close().then(() => { throw error; }); });
process.once("unhandledRejection", (error) => { void close().then(() => { throw error; }); });

server.listen(port, host, () => {
  console.log(`Serving sealed offline lifecycle deployments on http://${host}:${port}`);
});
