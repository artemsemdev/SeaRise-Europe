import type { ReleaseBootstrapState } from "./use-release-context";

export interface ReleaseScopeStatus {
  readonly title: string;
  readonly detail: string;
}

export function releaseScopeStatus(state: ReleaseBootstrapState): ReleaseScopeStatus {
  if (state.phase === "loading") {
    return Object.freeze({
      title: "Release validation pending",
      detail: "Scientific release status appears only after the pinned manifest is verified.",
    });
  }
  if (state.phase === "error") {
    return Object.freeze({
      title: "Release unavailable",
      detail: "No scientific outcome can be produced until the pinned release is verified.",
    });
  }
  switch (state.context.disposition) {
    case "synthetic-fixture":
      return Object.freeze({
        title: "Synthetic fixture",
        detail: "Demonstration data only; no public scientific release is claimed.",
      });
    case "private-engineering":
      return Object.freeze({
        title: "Private engineering candidate",
        detail: "Local validation only; not verified, public, signed, or approved for publication.",
      });
    case "public-promoted":
      return Object.freeze({
        title: "Public promoted release",
        detail: "Approved immutable release artifacts passed the required release validation.",
      });
    default:
      return state.context.disposition satisfies never;
  }
}
