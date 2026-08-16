import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type RefObject,
} from "react";
import type { ReleaseMethodology } from "../data/methodology-repository";
import type { ReleaseContext, ResolvedArtifact } from "../domain/release";
import "./MethodologyDialog.css";

export interface MethodologyDialogProps {
  readonly methodology: ReleaseMethodology | null;
  readonly release: ReleaseContext;
  readonly open: boolean;
  readonly onClose: () => void;
  /** The control that opened the dialog and must regain focus after it closes. */
  readonly triggerRef?: RefObject<HTMLElement | null>;
}

interface IntegrityLink {
  readonly label: string;
  readonly url: string;
}

const OUTCOME_DESCRIPTIONS: Readonly<Record<ReleaseMethodology["resultStates"][number], string>> = {
  ProjectionAvailable: "The exact release contains a projection for the selected scenario and horizon.",
  DataUnavailable: "The release has no usable projection value at the selected native source-grid location.",
  OutOfScope: "The selected point is outside the release's supported European geography.",
  UnsupportedGeography: "The selected point is in Europe but outside the supported coastal geography.",
};

const DISPOSITION_COPY: Readonly<Record<ReleaseMethodology["disposition"], string>> = {
  "synthetic-fixture": "Synthetic fixture — test data only. It is not a verified or promoted public release.",
  "private-engineering": "Private engineering release — local evaluation only. It is not verified or approved for public promotion.",
  "public-promoted": "Public promoted release — this publication disposition is declared by the pinned release.",
};

const EXCLUSION_LABELS: Readonly<Record<ReleaseMethodology["prohibitedClaims"][number], string>> = {
  flooding: "flooding",
  inundation: "inundation",
  "terrain-exposure": "terrain exposure",
  "flood-probability": "flood probability",
  "property-risk": "property risk",
};

function formatBuildDate(createdAt: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T/.exec(createdAt);
  if (!match) return createdAt;
  const months = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ] as const;
  return `${months[Number(match[2]) - 1]} ${Number(match[3])}, ${match[1]}`;
}

function optionalArtifact(release: ReleaseContext, artifactId: string | null | undefined): ResolvedArtifact | null {
  if (!artifactId) return null;
  return release.artifacts[artifactId] ?? null;
}

function integrityLinks(release: ReleaseContext): readonly IntegrityLink[] {
  const contracts = release.manifest.contractArtifacts;
  const candidates: readonly (readonly [string, ResolvedArtifact | null])[] = [
    ["STAC catalog", optionalArtifact(release, contracts.stacCatalog)],
    ["Checksums", optionalArtifact(release, contracts.checksums)],
    ["Base-release provenance", optionalArtifact(release, contracts.baseReleaseProvenance)],
    ["Browser-derivation provenance", optionalArtifact(release, contracts.browserDerivationProvenance)],
    ["Base-release signature", optionalArtifact(release, contracts.baseReleaseSignature)],
  ];
  return [
    { label: "Release manifest", url: release.manifestUrl },
    ...candidates.flatMap(([label, artifact]) => artifact ? [{ label, url: artifact.url }] : []),
  ];
}

function closeDialog(dialog: HTMLDialogElement): void {
  if (!dialog.open) return;
  try {
    dialog.close();
  } catch {
    dialog.removeAttribute("open");
  }
}

export function MethodologyDialog({
  methodology,
  release,
  open,
  onClose,
  triggerRef,
}: MethodologyDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);
  const titleId = useId();
  const descriptionId = useId();
  const trustedMethodology = methodology !== null &&
    methodology.dataReleaseId === release.dataReleaseId &&
    methodology.disposition === release.disposition &&
    methodology.methodologyVersion === release.methodologyVersion
    ? methodology
    : null;
  const visible = open && trustedMethodology !== null;

  useLayoutEffect(() => {
    const dialog = dialogRef.current;

    if (visible) {
      if (!dialog) return;
      if (!wasOpenRef.current) {
        openerRef.current = triggerRef?.current ?? (
          document.activeElement instanceof HTMLElement ? document.activeElement : null
        );
      }
      if (!dialog.open) {
        try {
          dialog.showModal();
        } catch {
          dialog.setAttribute("open", "");
        }
      }
      closeRef.current?.focus();
    } else {
      if (dialog) closeDialog(dialog);
      if (wasOpenRef.current) {
        const opener = triggerRef?.current ?? openerRef.current;
        queueMicrotask(() => opener?.focus());
      }
    }
    wasOpenRef.current = visible;
  }, [triggerRef, visible]);

  useEffect(() => () => {
    if (wasOpenRef.current) openerRef.current?.focus();
  }, []);

  if (!trustedMethodology) return null;

  const source = release.manifest.sources[0];
  const links = integrityLinks(release);
  const hasVisualOnlyPmtiles = Object.values(release.datasets).every((dataset) => {
    const visual = release.artifacts[dataset.visualArtifactId];
    return visual?.role === "projection-visual-pmtiles" && visual.scientificUse === "visual-only";
  });

  return (
    <dialog
      ref={dialogRef}
      className="methodology-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      data-release-disposition={trustedMethodology.disposition}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="methodology-dialog__header">
        <div>
          <p className="methodology-dialog__eyebrow">Release methodology</p>
          <h2 id={titleId}>Methodology and data</h2>
          <p id={descriptionId}>Release-scoped scientific method, source, limitations, and integrity references.</p>
        </div>
        <button ref={closeRef} type="button" className="methodology-dialog__close" onClick={onClose}>
          <span aria-hidden="true">×</span>
          <span className="methodology-dialog__close-label">Close methodology</span>
        </button>
      </div>

      <p className="methodology-dialog__disposition" role="status">
        {DISPOSITION_COPY[trustedMethodology.disposition]}
      </p>

      <section aria-labelledby={`${titleId}-release`}>
        <h3 id={`${titleId}-release`}>Pinned release</h3>
        <dl className="methodology-dialog__facts">
          <div><dt>Data release</dt><dd>{trustedMethodology.dataReleaseId}</dd></div>
          <div>
            <dt>Build date</dt>
            <dd><time dateTime={release.manifest.baseReleaseIdentity.createdAt}>{formatBuildDate(release.manifest.baseReleaseIdentity.createdAt)}</time></dd>
          </div>
          <div><dt>Methodology version</dt><dd>{trustedMethodology.methodologyVersion}</dd></div>
          <div><dt>Projection baseline</dt><dd>{trustedMethodology.baseline}</dd></div>
        </dl>
      </section>

      <section aria-labelledby={`${titleId}-lookup`}>
        <h3 id={`${titleId}-lookup`}>Exact lookup contract</h3>
        <p>
          The likely range uses quantile bands <strong>q0.167</strong>, <strong>q0.5</strong>, and <strong>q0.833</strong>.
          The browser selects the nearest native <strong>{trustedMethodology.lookup.nativeResolutionDegrees}° source-grid location</strong>
          {" "}within an inclusive <strong>{trustedMethodology.lookup.maximumDistanceKilometres} km</strong> limit.
        </p>
        <p>
          Interpolation, extrapolation, no-data substitution, and tide-gauge fallback are prohibited. The native 1°
          resolution does not resolve site-level conditions, and nearby places may use the same source-grid location.
        </p>
        {hasVisualOnlyPmtiles ? (
          <p>PMTiles is visual context only and is never used as the scientific lookup source.</p>
        ) : null}
      </section>

      <section aria-labelledby={`${titleId}-outcomes`}>
        <h3 id={`${titleId}-outcomes`}>Scientific outcomes</h3>
        <ul className="methodology-dialog__outcomes">
          {trustedMethodology.resultStates.map((outcome) => (
            <li key={outcome}><strong>{outcome}</strong><span>{OUTCOME_DESCRIPTIONS[outcome]}</span></li>
          ))}
        </ul>
      </section>

      <section aria-labelledby={`${titleId}-source`}>
        <h3 id={`${titleId}-source`}>Scientific source</h3>
        <dl className="methodology-dialog__facts">
          <div><dt>Title</dt><dd>{trustedMethodology.source.title}</dd></div>
          <div><dt>Source release</dt><dd>{source?.sourceRelease ?? "Not declared"}</dd></div>
          <div><dt>Role</dt><dd>Scientific source for the projection analysis, analytical, and visual release artifacts.</dd></div>
          <div><dt>Licence</dt><dd><a href={trustedMethodology.source.licence.url}>{trustedMethodology.source.licence.name} ({trustedMethodology.source.licence.spdxId})</a></dd></div>
          <div><dt>Acknowledgement</dt><dd>{trustedMethodology.source.attributionText}</dd></div>
          <div><dt>Source link</dt><dd><a href={trustedMethodology.source.sourceUrl}>{trustedMethodology.source.sourceUrl}</a></dd></div>
        </dl>
      </section>

      <section aria-labelledby={`${titleId}-limits`}>
        <h3 id={`${titleId}-limits`}>Limitations and product exclusions</h3>
        <ul>{trustedMethodology.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
        <p>This product does not provide:</p>
        <ul>{trustedMethodology.prohibitedClaims.map((claim) => <li key={claim}>{EXCLUSION_LABELS[claim]}</li>)}</ul>
      </section>

      <section aria-labelledby={`${titleId}-integrity`}>
        <h3 id={`${titleId}-integrity`}>Integrity and provenance</h3>
        <ul className="methodology-dialog__links">
          {links.map((link) => <li key={link.label}><a href={link.url}>{link.label}</a></li>)}
          <li><a href={trustedMethodology.decision.href}>{trustedMethodology.decision.id} scientific decision</a></li>
        </ul>
      </section>
    </dialog>
  );
}
