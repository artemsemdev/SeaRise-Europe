import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createReleaseDeliveryMiddleware } from "../../src/web/scripts/release-delivery-middleware.mjs";

export function sealedPreviewConfig({ webRoot, app, port, middleware, close }) {
  const { dataReleaseId } = JSON.parse(readFileSync(resolve(app, "build-identity.json"), "utf8"));
  const releaseDelivery = createReleaseDeliveryMiddleware({
    releaseRoot: resolve(app, "releases", dataReleaseId), releaseId: dataReleaseId,
    origin: `http://127.0.0.1:${port}`,
  });
  return {
    configFile: false, envDir: false, root: webRoot, build: { outDir: app },
    preview: { host: "127.0.0.1", port, strictPort: true,
      headers: { "Cache-Control": "no-cache", "Content-Encoding": "identity" } },
    plugins: [{ name: "sealed-local-demo", configurePreviewServer(active) {
      close(active);
      active.middlewares.use((request, response, next) => {
        if (new URL(request.url ?? "/", "http://127.0.0.1").pathname.startsWith("/atlas-data/")) {
          response.setHeader("Cache-Control", "no-store");
        }
        middleware(request, response, next);
      });
      active.middlewares.use(releaseDelivery);
    } }],
  };
}
