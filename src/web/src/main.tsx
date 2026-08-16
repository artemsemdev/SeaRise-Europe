import "@fontsource-variable/instrument-sans";
import "@fontsource/instrument-serif/400.css";
import "@fontsource/instrument-serif/400-italic.css";
import "@fontsource-variable/geist-mono";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { registerServiceWorkerAfterInteractivity } from "./offline/register-service-worker";
import "./styles.css";

if (__RELEASE_DISPOSITION__ === "private-engineering") {
  void import("./private-candidate-validation").then(({ installPrivateCandidateValidation }) =>
    installPrivateCandidateValidation(),
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("SeaRise root element is missing");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

registerServiceWorkerAfterInteractivity();
