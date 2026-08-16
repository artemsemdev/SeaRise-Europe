import type {
  InteractionSubjectV1,
  RuntimeCapabilityV2,
} from "../offline/contracts/policy";
import type { RuntimeCapabilityInspectionV1 } from "../offline/verified-resource-router";

export interface RuntimeCapabilityPort {
  readonly getSnapshot: () => RuntimeCapabilityV2 | null;
  readonly subscribe: (listener: () => void) => () => void;
  readonly selectSubject: (subject: InteractionSubjectV1) => void;
  readonly confirmCurrentInteractionAvailable: () => Promise<void>;
  readonly retry: () => Promise<void>;
  readonly requestUpdateAction: () => Promise<void>;
  readonly dispose: () => void;
}

export interface RuntimeUpdateActionPort {
  readonly requestAction: (capability: RuntimeCapabilityV2) => Promise<void>;
}

export interface RuntimeCapabilityControllerOptions {
  readonly initialSubject?: InteractionSubjectV1;
  readonly inspect: (
    subject: InteractionSubjectV1,
    options: RuntimeCapabilityInspectionV1,
  ) => Promise<RuntimeCapabilityV2>;
  readonly updateAction?: RuntimeUpdateActionPort;
}

function sameSubject(left: InteractionSubjectV1, right: InteractionSubjectV1): boolean {
  if (left.kind !== right.kind) return false;
  if (left.kind === "core" && right.kind === "core") return true;
  if (left.kind === "search" && right.kind === "search") {
    return left.shards.length === right.shards.length &&
      left.shards.every((shard, index) => shard === right.shards[index]);
  }
  return (left.kind === "assessment" || left.kind === "map") &&
    (right.kind === "assessment" || right.kind === "map") &&
    left.scenario === right.scenario && left.horizon === right.horizon;
}

/**
 * Publishes capability only after an exact inventory inspection. Online proof
 * is scoped to one interaction and can be supplied only by a completed
 * authoritative operation, never by navigator.onLine.
 */
export class RuntimeCapabilityController implements RuntimeCapabilityPort {
  readonly #inspect: RuntimeCapabilityControllerOptions["inspect"];
  readonly #updateAction: RuntimeUpdateActionPort | undefined;
  readonly #listeners = new Set<() => void>();
  #subject: InteractionSubjectV1;
  #snapshot: RuntimeCapabilityV2 | null = null;
  #networkProof = false;
  #generation = 0;
  #disposed = false;

  constructor(options: RuntimeCapabilityControllerOptions) {
    this.#inspect = options.inspect;
    this.#updateAction = options.updateAction;
    this.#subject = options.initialSubject ?? Object.freeze({ kind: "core" });
    void this.#refresh().catch(() => undefined);
  }

  readonly getSnapshot = (): RuntimeCapabilityV2 | null => this.#snapshot;

  readonly subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  readonly selectSubject = (subject: InteractionSubjectV1): void => {
    if (sameSubject(this.#subject, subject)) return;
    this.#subject = subject;
    this.#networkProof = false;
    this.#publish(null);
    void this.#refresh().catch(() => undefined);
  };

  readonly confirmCurrentInteractionAvailable = async (): Promise<void> => {
    this.#networkProof = true;
    await this.#refresh();
  };

  readonly retry = async (): Promise<void> => {
    await this.#refresh();
  };

  readonly requestUpdateAction = async (): Promise<void> => {
    if (!this.#snapshot || !this.#updateAction) return;
    await this.#updateAction.requestAction(this.#snapshot);
    await this.#refresh();
  };

  readonly dispose = (): void => {
    this.#disposed = true;
    this.#generation += 1;
    this.#listeners.clear();
  };

  async #refresh(): Promise<void> {
    const generation = ++this.#generation;
    const subject = this.#subject;
    const snapshot = await this.#inspect(subject, {
      authoritativeNetworkUsable: this.#networkProof,
    });
    if (this.#disposed || generation !== this.#generation || !sameSubject(subject, this.#subject)) return;
    this.#publish(snapshot);
  }

  #publish(snapshot: RuntimeCapabilityV2 | null): void {
    if (this.#snapshot === snapshot) return;
    this.#snapshot = snapshot;
    for (const listener of [...this.#listeners]) listener();
  }
}
