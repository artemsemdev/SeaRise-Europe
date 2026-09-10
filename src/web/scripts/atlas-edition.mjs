import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const marker = '<meta name="searise-atlas-edition" content="synthetic-fixture" />';

export function atlasEditionPlugin({ mode, repositoryRoot, buildRoot, loadLocalService = () => import("./real-local-atlas.mjs") }) {
  const edition = mode === "real-local" ? "real-local" : "synthetic-fixture";
  const expectedMarker = marker.replace("synthetic-fixture", edition);
  async function attach(server, preview) {
    if (preview && !readFileSync(resolve(buildRoot, "index.html"), "utf8").includes(expectedMarker)) {
      throw new Error(`Build the ${edition} edition before starting its preview.`);
    }
    if (edition !== "real-local") return;
    const host = preview ? server.config.preview.host : server.config.server.host;
    if (host !== undefined && !["127.0.0.1", "localhost", "::1"].includes(host)) {
      throw new Error("The real-local atlas must listen on a loopback host.");
    }
    const { createRealLocalAtlas } = await loadLocalService();
    const runtime = await createRealLocalAtlas({ repositoryRoot });
    server.middlewares.use(runtime.middleware);
    const shutdown = () => { void runtime.close(); };
    process.once("exit", shutdown);
    server.httpServer.once("close", () => {
      process.removeListener("exit", shutdown);
      shutdown();
    });
  }
  return {
    name: "explicit-atlas-edition",
    transformIndexHtml(html, context) {
      if (!["/", "/index.html"].includes(context.path)) return html;
      if (!html.includes(marker)) throw new Error("The Atlas entry must declare its edition.");
      return html.replace(marker, expectedMarker);
    },
    configureServer: (server) => attach(server, false),
    configurePreviewServer: (server) => attach(server, true),
  };
}
