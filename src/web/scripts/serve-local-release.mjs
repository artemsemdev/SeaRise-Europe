import { servePrivateCandidate } from "./local-candidate-binding.mjs";

const candidateRoot = process.env.SEARISE_LOCAL_CANDIDATE_ROOT;
const sourceGrid = process.env.SEARISE_LOCAL_SOURCE_GRID;
if (!candidateRoot || !sourceGrid) {
  throw new Error(
    "Set explicit SEARISE_LOCAL_CANDIDATE_ROOT and SEARISE_LOCAL_SOURCE_GRID absolute paths.",
  );
}

const active = await servePrivateCandidate({
  candidateRoot,
  sourceGrid,
  port: process.env.SEARISE_LOCAL_PORT,
});
console.log(
  `Private read-only binding for ${active.binding.releaseId}: ${active.binding.origin}`,
);
console.log("verified=false privateEngineeringOnly=true publicPromotionAuthorized=false");
process.once("exit", () => active.binding.cleanup());

let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  await active.close();
}
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    close().then(() => process.exit(0), () => process.exit(1));
  });
}
