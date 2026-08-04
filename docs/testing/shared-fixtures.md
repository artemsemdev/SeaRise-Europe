# Shared fixture ownership

Shared fixtures are serialized expected evidence, not generated copies of an
implementation's output. Python and TypeScript read the same file; each target
contains its own small adapter and the expected value is written once.

All fixtures conform to
[`tests/contracts/shared-fixture.schema.json`](../../tests/contracts/shared-fixture.schema.json)
and declare a stable ID, kind, owner, review status, methodology version,
purpose, cases, and source metadata when applicable.

## Kinds and authority

- `synthetic` proves code behavior only. It cannot pass a scientific gate.
- `source-sample` is a pinned real-source excerpt with licence, attribution,
  URL, and SHA-256. Redistribution must be reviewed.
- `golden` is independently controlled expected evidence with
  `approved-golden` review status and source metadata.
- `invalid` deliberately breaks a contract, geometry, artifact, or range.

The declared owner maintains format and intent. Science approves semantics and
golden expected values. Data approves extraction/reproducibility. Security
reviews licence, integrity, provenance, and public-delivery fixtures. Frontend
and platform review consumer and delivery behavior respectively.

## Versioning and changes

Fixture IDs end in `-v<major>`. Make a new major fixture when meaning, source,
methodology, coordinate interpretation, or expected public outcome changes.
Additive cases that preserve meaning can update the current file, but the PR
must show every consumer and independent control passing.

Never generate expected states with the function under test. A real-source
golden must record how the control was derived and who approved it. If review is
pending, use `pending-science-review`; never label it approved to unblock CI.

## Cross-language consumption

The current characterization fixture is
[`five-state-characterization-v1.json`](../../tests/fixtures/tdd/five-state-characterization-v1.json).
It is intentionally synthetic and marked `characterization-only`.

- Python exercises the target pipeline/domain rule with table boundaries.
- TypeScript exercises the target browser rule from the same JSON.
- C# is an independent legacy control while that implementation exists.

Test builders translate serialized fields into domain-intent inputs. They do
not import or reproduce legacy HTTP DTOs, database entities, or blob paths.

## Representative evidence, not mocks

Mocks are allowed at process boundaries when the assertion concerns caller
behavior: timeout handling, abort propagation, retry limits, or provider error
mapping. They are not acceptable substitutes for representative fixtures in:

- scientific arrays, nodata, geometry, coordinate-to-cell, and class meaning;
- manifest/release schemas, checksums, provenance, and licence metadata;
- COG/PMTiles byte-range and corruption behavior;
- public-origin headers, cache, CORS, rollback, and zero-runtime-API journeys.

Those areas require a small checked-in representative fixture or an explicitly
tiered integration test. Large/raw source data stays outside Git.
