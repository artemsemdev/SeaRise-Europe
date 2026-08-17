/// <reference lib="webworker" />

import { createServiceWorkerRuntime, type EmbeddedPrecacheV3 } from "./service-worker-runtime";
import { createServiceWorkerClientAuthority } from "./service-worker-client-authority";

declare const __SEARISE_PRECACHE_JSON__: string;

const worker = self as unknown as ServiceWorkerGlobalScope;
const runtime = createServiceWorkerRuntime(
  JSON.parse(__SEARISE_PRECACHE_JSON__) as EmbeddedPrecacheV3,
  {
    origin: worker.location.origin,
    caches: worker.caches,
    fetch: worker.fetch.bind(worker),
  },
);
const clientAuthority = createServiceWorkerClientAuthority(runtime.pair, {
  indexedDB: worker.indexedDB,
  clients: worker.clients,
});

worker.addEventListener("install", (event) => event.waitUntil(runtime.install()));
worker.addEventListener("activate", () => undefined);
worker.addEventListener("fetch", (event) => {
  const response = runtime.fetch(event.request);
  if (response) event.respondWith(response);
});
worker.addEventListener("message", (event) => {
  const response = runtime.message(event.data);
  if (response) {
    const port = event.ports[0];
    if (port) port.postMessage(response);
    else if (event.source && "postMessage" in event.source) event.source.postMessage(response);
    return;
  }
  event.waitUntil(clientAuthority.message(
    event.data,
    event.source && "id" in event.source && "type" in event.source
      ? event.source as unknown as Readonly<{ id: string; type: string }>
      : null,
    event.ports.length,
  ).then((authorityResponse) => {
    if (authorityResponse && event.ports.length === 1) event.ports[0]!.postMessage(authorityResponse);
  }));
});
