import { createServer } from "node:http";
import { resolve } from "node:path";
import { createReleaseDeliveryMiddleware } from "./release-delivery-middleware.mjs";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const releaseRoot = resolve(import.meta.dirname, `../dist/releases/${releaseId}`);
const origin = "http://127.0.0.1:4173";
const port = 8091;
const middleware = createReleaseDeliveryMiddleware({ releaseRoot, releaseId, origin });
createServer((request, response) => {
  middleware(request, response, () => response.writeHead(404).end());
}).listen(port, "127.0.0.1", () => {
  console.log(`Serving committed synthetic release on http://127.0.0.1:${port}`);
});
