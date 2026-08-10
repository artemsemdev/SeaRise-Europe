# Release gate report contracts

`v1/gate-report.schema.json` is the machine-readable contract for deciding
whether an immutable release candidate may advance. It is independent of the
immutable public data contracts in `contracts/release/v1`.

The contract records candidate and data-release identity, the authority making
the decision, closed check statuses and stop reasons, metric targets and
measurements, and content-addressed evidence. A `not-measured` check is a
blocking result; it is never interpreted as a pass.
Only an explicit approved owner decision may set `releasable` to `true`, and
then only when every check passes. Automation can report validation but cannot
release a candidate.

Critical integrity, scientific, rights, schema, cross-runtime,
reproducibility, measurement, approval, and supply-chain stop reasons are
always non-waivable. Only an owner-controlled `metric-target-missed` check may
be classified as waivable, but v1 intentionally has no waiver record and every
blocked check still prevents release. Adding expiring evidence-bound waivers
would require a new contract version.

Consumers must also apply the matching semantic validators in
`searise_pipeline.gate_report` and the frontend contract library. They enforce
deterministic check/evidence order, target-to-status agreement, aggregate
automation status, exact stop-reason aggregation, owner authority, and the
fail-closed release rule. The Markdown renderer validates those semantics
before producing the committed byte-stable human view.
