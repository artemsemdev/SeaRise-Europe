import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import AtlasApp from "./AtlasApp";
import { createAtlasDataSource } from "./create-data-source";

// An unavailable local service remains an error in this edition. Selection
// never depends on service discovery, saved browser state, or a query string.
const dataSource = createAtlasDataSource({
  edition: import.meta.env.MODE === "real-local" ? "real-local" : "synthetic-fixture",
});
const root = document.getElementById("root");
if (!root) throw new Error("SeaRise root element is missing");
createRoot(root).render(<StrictMode><AtlasApp dataSource={dataSource} /></StrictMode>);
