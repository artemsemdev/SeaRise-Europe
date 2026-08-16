import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ReleaseMethodology } from "../data/methodology-repository";
import { ReleaseContext, type ReleaseDisposition } from "../domain/release";
import { fixtureReleaseContext } from "../test/release-fixture";
import { MethodologyDialog } from "./MethodologyDialog";

function verifiedMethodology(context: ReleaseContext): ReleaseMethodology {
  // This is the exact immutable value asserted by methodology-repository.test.ts.
  // Component tests intentionally start at that verified repository boundary.
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    disposition: context.disposition,
    methodologyVersion: "ar6-regional-projection-v1",
    baseline: "1995-2014 mean",
    likelyRange: Object.freeze({ confidence: "medium", lowerQuantile: 0.167, medianQuantile: 0.5, upperQuantile: 0.833 }),
    lookup: Object.freeze({
      operator: "nearest-source-grid-location",
      nativeResolutionDegrees: 1,
      maximumDistanceKilometres: 100,
      distanceLimitInclusive: true,
      interpolation: "prohibited",
      extrapolation: "prohibited",
      nodataSubstitution: "prohibited",
      tideGaugeFallback: "prohibited",
    }),
    resultStates: ["ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography"] as const,
    limitations: [
      "Reports regional relative sea-level projection, not an absolute water level.",
      "Does not model flooding, terrain exposure, probability, or property risk.",
    ],
    prohibitedClaims: ["flooding", "inundation", "terrain-exposure", "flood-probability", "property-risk"] as const,
    decision: Object.freeze({
      id: "ADR-024",
      href: `https://github.com/artemsemdev/SeaRise-Europe/blob/${context.manifest.baseReleaseIdentity.codeRevision}/docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md`,
    }),
    source: Object.freeze({
      title: "IPCC AR6 Sea Level Projections",
      attributionText: "Garner et al. (2021), IPCC AR6 Sea Level Projections, version 20210809, doi:10.5281/zenodo.5914709.",
      sourceUrl: "https://doi.org/10.5281/zenodo.6382554",
      licence: Object.freeze({
        name: "Creative Commons Attribution 4.0 International",
        spdxId: "CC-BY-4.0",
        url: "https://creativecommons.org/licenses/by/4.0/",
      }),
    }),
  });
}

function withDisposition(context: ReleaseContext, disposition: ReleaseDisposition): ReleaseContext {
  return new ReleaseContext({
    manifest: context.manifest,
    manifestUrl: context.manifestUrl,
    disposition,
    artifacts: { ...context.artifacts },
    datasets: { ...context.datasets },
  });
}

function ControlledDialog({
  methodology,
  release,
}: Readonly<{ methodology: ReleaseMethodology | null; release: ReleaseContext }>) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>Review methodology</button>
      <MethodologyDialog
        methodology={methodology}
        release={release}
        open={open}
        onClose={() => setOpen(false)}
        triggerRef={triggerRef}
      />
    </>
  );
}

let context: ReleaseContext;
let methodology: ReleaseMethodology;

beforeEach(async () => {
  context = await fixtureReleaseContext();
  methodology = verifiedMethodology(context);
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("release methodology dialog", () => {
  it("opens with deterministic close-button focus, closes by button, and restores trigger focus", async () => {
    const user = userEvent.setup();
    render(<ControlledDialog methodology={methodology} release={context} />);
    const trigger = screen.getByRole("button", { name: "Review methodology" });

    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Methodology and data" });
    const close = screen.getByRole("button", { name: "Close methodology" });
    expect(dialog).toHaveAttribute("aria-describedby");
    expect(close).toHaveFocus();

    await user.click(close);
    await waitFor(() => expect(dialog).not.toHaveAttribute("open"));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("handles the native Escape cancel event without allowing uncontrolled closure", async () => {
    const user = userEvent.setup();
    render(<ControlledDialog methodology={methodology} release={context} />);
    const trigger = screen.getByRole("button", { name: "Review methodology" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Methodology and data" });

    const cancel = new Event("cancel", { cancelable: true });
    fireEvent(dialog, cancel);
    expect(cancel.defaultPrevented).toBe(true);
    await waitFor(() => expect(dialog).not.toHaveAttribute("open"));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("renders only verified release content and current-context integrity links", async () => {
    render(<MethodologyDialog methodology={methodology} release={context} open onClose={() => undefined} />);

    expect(screen.getByText(context.dataReleaseId)).toBeVisible();
    expect(screen.getByText("August 10, 2026")).toHaveAttribute("datetime", context.manifest.baseReleaseIdentity.createdAt);
    expect(screen.getByText("ar6-regional-projection-v1")).toBeVisible();
    expect(screen.getByText("IPCC AR6 Sea Level Projections")).toBeVisible();
    expect(screen.getByText("20210809")).toBeVisible();
    expect(screen.getByText(/Garner et al\. \(2021\)/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Creative Commons Attribution 4.0 International/ })).toHaveAttribute(
      "href",
      methodology.source.licence.url,
    );
    expect(screen.getByRole("link", { name: methodology.source.sourceUrl })).toHaveAttribute(
      "href",
      methodology.source.sourceUrl,
    );

    const expectedLinks = [
      ["Release manifest", context.manifestUrl],
      ["STAC catalog", context.artifact(context.manifest.contractArtifacts.stacCatalog).url],
      ["Checksums", context.artifact(context.manifest.contractArtifacts.checksums).url],
      ["Base-release provenance", context.artifact(context.manifest.contractArtifacts.baseReleaseProvenance!).url],
      ["Browser-derivation provenance", context.artifact(context.manifest.contractArtifacts.browserDerivationProvenance).url],
      ["Base-release signature", context.artifact(context.manifest.contractArtifacts.baseReleaseSignature!).url],
      ["ADR-024 scientific decision", methodology.decision.href],
    ] as const;
    expectedLinks.forEach(([name, href]) => {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    });
  });

  it("shows the exact four outcomes and the native-grid lookup boundaries", () => {
    const { container } = render(
      <MethodologyDialog methodology={methodology} release={context} open onClose={() => undefined} />,
    );

    methodology.resultStates.forEach((outcome) => expect(screen.getByText(outcome)).toBeVisible());
    expect(screen.getByText("OutOfScope").closest("li")).toHaveTextContent(
      "The selected point is inside the supported Europe geometry but outside the versioned coastal analysis area.",
    );
    expect(screen.getByText("UnsupportedGeography").closest("li")).toHaveTextContent(
      "The selected point is outside the versioned Europe support geometry.",
    );
    expect(screen.getAllByRole("listitem").filter((item) =>
      methodology.resultStates.some((outcome) => item.textContent?.startsWith(outcome)),
    )).toHaveLength(4);
    const lookup = screen.getByRole("heading", { name: "Exact lookup contract" }).parentElement;
    expect(lookup).toHaveTextContent(/q0\.167, q0\.5, and q0\.833/);
    expect(lookup).toHaveTextContent(/nearest native 1° source-grid location/);
    expect(lookup).toHaveTextContent(/inclusive 100 km limit/);
    expect(screen.getByText(/Interpolation, extrapolation/)).toHaveTextContent(
      "Interpolation, extrapolation, no-data substitution, and tide-gauge fallback are prohibited.",
    );
    expect(screen.getByText(/PMTiles is visual context only/)).toBeVisible();

    expect(container.querySelectorAll(".methodology-dialog__outcomes > li")).toHaveLength(4);
  });

  it.each([
    ["synthetic-fixture", "Synthetic fixture — test data only. It is not a verified or promoted public release."],
    ["private-engineering", "Private engineering release — local evaluation only. It is not verified or approved for public promotion."],
    ["public-promoted", "Public promoted release — this publication disposition is declared by the pinned release."],
  ] as const)("presents the %s disposition without inventing promotion", async (disposition, disclosure) => {
    const release = withDisposition(context, disposition);
    const releaseMethodology = verifiedMethodology(release);
    render(<MethodologyDialog methodology={releaseMethodology} release={release} open onClose={() => undefined} />);

    expect(screen.getByRole("status")).toHaveTextContent(disclosure);
    expect(screen.getByRole("dialog")).toHaveAttribute("data-release-disposition", disposition);
  });

  it("renders no dialog or scientific constants when verified methodology is absent", () => {
    const { container } = render(
      <MethodologyDialog methodology={null} release={context} open onClose={() => undefined} />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("q0.167")).not.toBeInTheDocument();
    expect(screen.queryByText("ProjectionAvailable")).not.toBeInTheDocument();
  });

  it("fails closed when methodology and release identities do not match", () => {
    const otherDisposition = withDisposition(context, "private-engineering");
    const { container } = render(
      <MethodologyDialog methodology={methodology} release={otherDisposition} open onClose={() => undefined} />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
