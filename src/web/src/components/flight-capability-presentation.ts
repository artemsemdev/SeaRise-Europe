import type { UpdateCapabilityV1 } from "../offline/contracts/policy";

export interface FlightUpdateAlertPresentation {
  readonly className: "application-technical-alert";
  readonly role: "status";
  readonly ariaLive: "polite";
  readonly state: Exclude<UpdateCapabilityV1["state"], "current">;
  readonly message: string;
  readonly action: string | null;
}

function updateMessage(update: UpdateCapabilityV1): string | null {
  switch (update.state) {
    case "current": return null;
    case "update-available":
      return `Update available for ${update.candidate.dataReleaseId}. The current version remains active.`;
    case "installing":
      return `Preparing update ${update.candidate.dataReleaseId}. The current version remains active.`;
    case "ready-to-activate":
      return "Update ready. Close all SeaRise tabs and reopen to use it.";
    case "activation-blocked":
      return `Update blocked. ${update.reason} The current version remains active.`;
    case "failed":
      return `Update failed. The current version remains active. ${update.reason}`;
  }
}

function updateAction(update: UpdateCapabilityV1): string | null {
  switch (update.state) {
    case "update-available": return "Prepare update";
    case "activation-blocked":
    case "failed": return "Retry update";
    case "current":
    case "installing":
    case "ready-to-activate": return null;
  }
}

/** One production presentation contract shared by React and browser layout evidence. */
export function flightUpdateAlertPresentation(
  update: UpdateCapabilityV1,
): FlightUpdateAlertPresentation | null {
  const message = updateMessage(update);
  if (!message || update.state === "current") return null;
  return Object.freeze({
    className: "application-technical-alert",
    role: "status",
    ariaLive: "polite",
    state: update.state,
    message,
    action: updateAction(update),
  });
}
