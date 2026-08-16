import { useState } from "react";
import type {
  MissingRequirementV2,
  RuntimeCapabilityV2,
  UpdateCapabilityV1,
} from "../offline/contracts/policy";

interface CapabilityActions {
  readonly capability: RuntimeCapabilityV2 | null;
  readonly onRetry: () => Promise<void>;
  readonly onUpdateAction: () => Promise<void>;
}

function missingClass(requirement: MissingRequirementV2): string {
  switch (requirement.kind) {
    case "whole": return "release resource";
    case "range": return "projection data range";
    case "network-only": return "visual map tiles";
  }
}

function missingResourceClasses(missing: readonly MissingRequirementV2[]): string {
  return [...new Set(missing.map(missingClass))].join(", ");
}

function offlineLabel(capability: RuntimeCapabilityV2): string | null {
  if (capability.data.state !== "available-offline" || capability.subject.kind === "map") return null;
  switch (capability.subject.kind) {
    case "search": return "Search available offline";
    case "assessment": return "Available offline for this assessment";
    case "core": return "Available offline";
  }
}

/** The canonical Flight header permits one conditional offline chip only. */
export function FlightCapabilityPill({ capability }: Pick<CapabilityActions, "capability">) {
  if (!capability) return null;
  const label = offlineLabel(capability);
  return label ? <span className="release-pill" data-capability-state="available-offline">{label}</span> : null;
}

function updateMessage(update: UpdateCapabilityV1): string | null {
  switch (update.state) {
    case "current": return null;
    case "update-available":
      return `Update available for ${update.candidate.dataReleaseId}. The current version remains active.`;
    case "installing":
      return `Preparing update ${update.candidate.dataReleaseId}. The current version remains active.`;
    case "ready-to-activate":
      return `Update ready. Reload to use ${update.candidate.dataReleaseId}.`;
    case "activation-blocked":
      return `Update blocked. ${update.reason} The current version remains active.`;
    case "failed":
      return `Update failed. The current version remains active. ${update.reason}`;
  }
}

function updateAction(update: UpdateCapabilityV1): string | null {
  switch (update.state) {
    case "update-available": return "Prepare update";
    case "ready-to-activate": return "Reload to update";
    case "activation-blocked":
    case "failed": return "Retry update";
    case "current":
    case "installing": return null;
  }
}

/** Technical, connection, storage, and update state stays in Flight's alert slot. */
export function FlightCapabilityAlerts({
  capability,
  onRetry,
  onUpdateAction,
}: CapabilityActions) {
  const [pending, setPending] = useState<"retry" | "update" | null>(null);
  const [actionError, setActionError] = useState("");
  if (!capability) return null;

  const run = async (kind: "retry" | "update", action: () => Promise<void>): Promise<void> => {
    setPending(kind);
    setActionError("");
    try {
      await action();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Capability action failed.");
    } finally {
      setPending(null);
    }
  };

  const updateCopy = updateMessage(capability.update);
  const updateButton = updateAction(capability.update);
  return (
    <>
      {capability.data.state === "connection-required" ? (
        <div className="application-technical-alert" role="alert" data-capability-state="connection-required">
          <strong>Connection required.</strong>{" "}
          Missing {missingResourceClasses(capability.data.missing)} for this exact interaction. No substitute was used.
          <button
            type="button"
            disabled={pending !== null}
            title={capability.data.missing.map(({ identity }) => identity).join(", ")}
            onClick={() => void run("retry", onRetry)}
          >
            {pending === "retry" ? "Checking…" : "Retry availability"}
          </button>
        </div>
      ) : null}
      {capability.data.state === "degraded-storage" ? (
        <div className="application-technical-alert" role="alert" data-capability-state="degraded-storage">
          <strong>Browser storage degraded ({capability.data.reason}).</strong>{" "}
          The current accepted result remains visible. New data may require a connection.
        </div>
      ) : null}
      {updateCopy ? (
        <div className="application-technical-alert" role="status" aria-live="polite" data-update-state={capability.update.state}>
          {updateCopy}
          {updateButton ? (
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => void run("update", onUpdateAction)}
            >
              {pending === "update" ? "Working…" : updateButton}
            </button>
          ) : null}
        </div>
      ) : null}
      {actionError ? (
        <div className="application-technical-alert" role="alert">
          <strong>Capability action failed.</strong> {actionError}{" "}
          This is a technical failure, not a scientific outcome.
        </div>
      ) : null}
    </>
  );
}
