import { EventEmitter } from "node:events";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { atlasEditionPlugin } from "./atlas-edition.mjs";

const marker = '<meta name="searise-atlas-edition" content="synthetic-fixture" />';
const directories = [];
afterEach(() => directories.splice(0).forEach((path) => rmSync(path, { recursive: true })));
function harness(mode = "production", host = "127.0.0.1") {
  const root = mkdtempSync(resolve(tmpdir(), "atlas-edition-")); directories.push(root);
  writeFileSync(resolve(root, "index.html"), marker);
  const close = vi.fn(async () => {}), middleware = vi.fn();
  const createRealLocalAtlas = vi.fn(async () => ({ close, middleware }));
  const loadLocalService = vi.fn(async () => ({ createRealLocalAtlas }));
  const plugin = atlasEditionPlugin({ mode, repositoryRoot: root, buildRoot: root, loadLocalService });
  const server = { config: { server: { host }, preview: { host } }, httpServer: new EventEmitter(), middlewares: { use: vi.fn() } };
  return { root, plugin, server, close, middleware, loadLocalService, createRealLocalAtlas };
}

describe("explicit Atlas edition activation", () => {
  it("runs the default development and preview without loading a local service", async () => {
    const value = harness();
    await value.plugin.configureServer(value.server);
    await value.plugin.configurePreviewServer(value.server);
    expect(value.loadLocalService).not.toHaveBeenCalled();
  });
  it("only transforms the Atlas document and binds its edition", () => {
    const { plugin } = harness("real-local");
    expect(plugin.transformIndexHtml(marker, { path: "/index.html" })).toContain('content="real-local"');
    expect(plugin.transformIndexHtml("reference", { path: "/projections/index.html" })).toBe("reference");
    expect(() => plugin.transformIndexHtml("missing", { path: "/" })).toThrow(/declare its edition/);
  });
  it("starts one explicit service and closes it with the server", async () => {
    const value = harness("real-local");
    await value.plugin.configureServer(value.server);
    expect(value.createRealLocalAtlas).toHaveBeenCalledExactlyOnceWith({ repositoryRoot: value.root });
    expect(value.server.middlewares.use).toHaveBeenCalledWith(value.middleware);
    value.server.httpServer.emit("close");
    expect(value.close).toHaveBeenCalledOnce();
  });
  it("refuses a mismatched built edition before any data access", async () => {
    const value = harness("real-local");
    await expect(value.plugin.configurePreviewServer(value.server)).rejects.toThrow(/Build the real-local edition/);
    expect(value.loadLocalService).not.toHaveBeenCalled();
  });
  it.each([true, "0.0.0.0", "::", "192.168.1.10"])("refuses an exposed real-local listener %s", async (host) => {
    const value = harness("real-local", host);
    await expect(value.plugin.configureServer(value.server)).rejects.toThrow(/loopback/);
    expect(value.loadLocalService).not.toHaveBeenCalled();
  });
});
