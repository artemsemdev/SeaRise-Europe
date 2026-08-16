import { runtimeConfig } from "../config";

export type WorkerRegistrationResult =
  | "scheduled"
  | "refused-private-engineering"
  | "disabled-development"
  | "unsupported";

interface RegistrationEnvironment {
  readonly production: boolean;
  readonly releaseDisposition: typeof runtimeConfig.releaseDisposition;
  readonly serviceWorker: Pick<ServiceWorkerContainer, "register"> | undefined;
  readonly readyState: DocumentReadyState;
  addLoadListener(listener: () => void): void;
  requestIdle(listener: () => void): void;
}

function browserEnvironment(): RegistrationEnvironment {
  return {
    production: import.meta.env.PROD,
    releaseDisposition: runtimeConfig.releaseDisposition,
    serviceWorker: navigator.serviceWorker,
    readyState: document.readyState,
    addLoadListener: (listener) => window.addEventListener("load", listener, { once: true }),
    requestIdle: (listener) => {
      const idle = (window as Window & { requestIdleCallback?: typeof window.requestIdleCallback })
        .requestIdleCallback;
      if (idle) idle.call(window, listener, { timeout: 2_000 });
      else globalThis.setTimeout(listener, 0);
    },
  };
}

export function registerServiceWorkerAfterInteractivity(
  environment: RegistrationEnvironment = browserEnvironment(),
): WorkerRegistrationResult {
  if (environment.releaseDisposition === "private-engineering") return "refused-private-engineering";
  if (!environment.production) return "disabled-development";
  if (!environment.serviceWorker) return "unsupported";

  const register = () => environment.requestIdle(() => {
    void environment.serviceWorker!.register("/service-worker.js", {
      scope: "/",
      type: "module",
      updateViaCache: "none",
    }).catch(() => undefined);
  });
  if (environment.readyState === "complete") register();
  else environment.addLoadListener(register);
  return "scheduled";
}
