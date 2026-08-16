/// <reference lib="webworker" />

import { createServiceWorkerRuntime, type EmbeddedPrecacheV2 } from "./service-worker-runtime";

declare const __SEARISE_PRECACHE_JSON__: string;

const worker = self as unknown as ServiceWorkerGlobalScope;
const runtime = createServiceWorkerRuntime(
  JSON.parse(__SEARISE_PRECACHE_JSON__) as EmbeddedPrecacheV2,
  {
    origin: worker.location.origin,
    caches: worker.caches,
    fetch: worker.fetch.bind(worker),
  },
);

worker.addEventListener("install", (event) => event.waitUntil(runtime.install()));
worker.addEventListener("activate", () => undefined);
worker.addEventListener("fetch", (event) => {
  const response = runtime.fetch(event.request);
  if (response) event.respondWith(response);
});
worker.addEventListener("message", (event) => {
  const response = runtime.message(event.data);
  if (!response) return;
  const port = event.ports[0];
  if (port) port.postMessage(response);
  else if (event.source && "postMessage" in event.source) event.source.postMessage(response);
});
