import type { RuntimeCapabilityV2, UpdateCapabilityV1 } from "./contracts/policy";
import type { AppReleasePairV1 } from "./contracts/keys";
import {
  StaticHostUpdateCoordinator,
  type StaticUpdateCoordinatorStateV1,
} from "./update-coordinator";
import type { BrowserUpdateCoordinator } from "../application/browser-runtime";

export interface StaticUpdateCandidateSource {
  readonly candidate: () => AppReleasePairV1 | null | Promise<AppReleasePairV1 | null>;
}
function presentation(
  state: StaticUpdateCoordinatorStateV1 | null,
  candidate: AppReleasePairV1 | null,
): UpdateCapabilityV1 {
  if (state?.phase === "close-and-reopen-required") {
    return Object.freeze({ state: "ready-to-activate", candidate: state.intent.candidate.pair });
  }
  if (state?.phase === "preparing" || state?.phase === "waiting-candidate-verified" ||
      state?.phase === "recording-close-and-reopen-intent") {
    const activeCandidate = "candidate" in state ? state.candidate.pair : candidate;
    return activeCandidate
      ? Object.freeze({ state: "installing", candidate: activeCandidate })
      : Object.freeze({ state: "current" });
  }
  if (state?.phase === "failed" || state?.phase === "adapter-stalled" ||
      state?.phase === "rollback-failed") {
    return Object.freeze({ state: "failed", reason: state.message });
  }
  if (state?.phase === "mutation-busy" || state?.phase === "deployment-required") {
    return Object.freeze({ state: "activation-blocked", reason: state.message });
  }
  return candidate
    ? Object.freeze({ state: "update-available", candidate })
    : Object.freeze({ state: "current" });
}

/**
 * Adapts the verified static-host update state machine to Flight capability.
 * It never reloads, activates a worker, or invents candidate evidence.
 */
export class StaticUpdateCapabilityCoordinator implements BrowserUpdateCoordinator {
  readonly #coordinator: StaticHostUpdateCoordinator;
  readonly #source: StaticUpdateCandidateSource;
  #candidate: AppReleasePairV1 | null = null;

  constructor(coordinator: StaticHostUpdateCoordinator, source: StaticUpdateCandidateSource) {
    this.#coordinator = coordinator;
    this.#source = source;
  }

  readonly inspect = async (): Promise<UpdateCapabilityV1> => {
    this.#candidate = await this.#source.candidate();
    return presentation(this.#coordinator.state(), this.#candidate);
  };

  readonly requestAction = async (capability: RuntimeCapabilityV2): Promise<void> => {
    if (capability.update.state === "ready-to-activate") return;
    const candidate = "candidate" in capability.update ? capability.update.candidate : this.#candidate;
    if (!candidate) throw new Error("No verified static update candidate is available.");
    const prepared = await this.#coordinator.prepareUpdate(candidate);
    if (prepared.phase === "waiting-candidate-verified") {
      await this.#coordinator.confirmUpdate(prepared.confirmationToken);
    }
  };
}
