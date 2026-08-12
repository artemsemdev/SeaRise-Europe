# Security Policy

## Project status

SeaRise Europe has no supported production release yet. The default branch
contains a legacy local demonstration stack and an accepted static-first target
architecture. The demo uses synthetic exposure data and is not an operational
climate or emergency service.

Security review applies to all tracked code, data-processing logic,
infrastructure, dependencies, generated artifact contracts, and documentation.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

1. Use GitHub private vulnerability reporting for this repository when
   available.
2. Otherwise contact the maintainer privately through GitHub before disclosure.

Include the affected revision and paths, reproduction steps, realistic impact,
and any known workaround. Do not include real credentials or sensitive user
data in the report.

Target response times:

- acknowledgement within 5 business days;
- initial triage within 10 business days.

## Security boundaries

The accepted production architecture has no application API, user accounts, or
runtime database. Public static files are intentionally readable. Integrity,
privacy, supply chain, and hosting configuration remain security concerns.

Report issues involving:

- committed or exposed secrets;
- dependency or build-pipeline compromise;
- malicious or substituted release artifacts;
- incorrect checksums, provenance, or signatures;
- overly broad cloud credentials, CORS, or Content Security Policy;
- cross-site scripting or unsafe rendering of search/data fields;
- service-worker cache poisoning or mixed data releases;
- unintended collection of search queries or coordinates;
- source-licence or attribution errors that make publication unsafe;
- denial-of-wallet behaviour in object-storage requests.

## Secret handling

- No real secret belongs in Git, frontend build variables, public manifests, or
  generated static assets.
- Local secrets use ignored environment files.
- CI publishing uses protected environments and least-privilege credentials.
- Keyless Cosign signing is preferred so no long-lived signing key is stored in
  the repository.
- If a credential is committed, revoke it first, then remove it from the current
  tree and coordinate history cleanup privately.

## Release trust chain

The Phase 1 trust boundary is commit and byte based. A controlled offline build
produces an immutable candidate; a protected, first-attempt workflow verifies
the complete candidate byte gate, signs the exact manifest and provenance with
keyless Cosign, and an independent job verifies the expected repository,
workflow, and OIDC issuer. After any public upload, run
`scripts/release/verify_public_signed_subjects.py` against the final HTTPS URLs.
That hook reruns cryptographic verification and accepts only exact public bytes.

A signature proves subject integrity and signing identity, not scientific
correctness, protected-environment configuration, publication approval, or
continuous availability. A failed signing, verification, or readback gate must
leave the previous verified release active; do not repair or overwrite a failed
candidate in place. Verification and public-readback receipts must be assigned
the same externally enforced retention period as the candidate they identify.
Local file modes do not establish or enforce that storage policy.

After both verification gates pass, use
`scripts/release/retain_release_evidence.py` to create the exact
`<dataReleaseId>/supply-chain` handoff. The command copies the manifest,
finalized evidence, cryptographic-verification receipt, and public-readback
receipt into one descriptor-validated, initially read-only tree and writes a
canonical handoff receipt. The command proves an atomic local no-overwrite
commit, not release-lifetime retention, deletion prevention, or co-retention
with published data. Apply and audit those controls in the external release
store. The retained verification receipts remain audit records produced by
their separate verifier gates; this handoff does not reauthenticate those
gates or grant production, publication, or scientific approval.

## Supported versions

There are no versioned public releases. Security fixes target the default branch
until the first signed static release is published. Each future release manifest
must identify the application commit, data release, dependency/build versions,
checksums, and provenance used to create it.
