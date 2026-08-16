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
- `golden` is expected evidence independently extracted from a pinned source,
  with source hashes, reader/generator identity, provenance, and registered
  tolerances.
- `invalid` deliberately breaks a contract, geometry, artifact, or range.

The declared owner maintains format and intent. Source contracts define
semantics; independent extraction and a separate production reader prove the
golden values without an absent scientific reviewer. Security checks licence,
integrity, provenance, and public-delivery fixtures. Frontend and platform
tests verify consumer and delivery behavior. Only the project owner records a
release disposition, after automated fixture and release validation passes.

## Versioning and changes

Fixture IDs end in `-v<major>`. Make a new major fixture when meaning, source,
methodology, coordinate interpretation, or expected public outcome changes.
Additive cases that preserve meaning can update the current file, but the PR
must show every consumer and independent control passing.

Never generate expected values with the function under test. A real-source
golden records the pinned source, independent reader and generator, extraction
parameters, checksums, and derivation date. CI may prove parity but cannot
record the owner release disposition.

## Cross-language consumption

The historical v1 characterization fixture is
[`five-state-characterization-v1.json`](../../tests/fixtures/tdd/five-state-characterization-v1.json).
It is intentionally synthetic and marked `characterization-only`; it protects
the retiring legacy path and is not the target projection contract.

Active projection parity uses
[`ar6-lookup-goldens.json`](../../src/pipeline/science/evidence/ar6-lookup-goldens.json),
independently extracted with the pinned netCDF4 reader. Production Python and
TypeScript verify the same source IDs, distances, quantiles, states, and reason
codes. C# and the five-state fixture remain legacy controls until that runtime
is removed.

The neutral
[`ar6-four-outcome-parity-v1.json`](../../src/pipeline/science/evidence/ar6-four-outcome-parity-v1.json)
control proves all and only the four ADR-024 outcomes in both runtimes. It is a
behavior-only synthetic fixture: its `DataUnavailable` case reads a three-band
nodata cell from the committed COG, but it is not public scientific-release
evidence.

Test builders translate serialized fields into domain-intent inputs. They do
not import or reproduce legacy HTTP DTOs, database entities, or blob paths.

## Representative evidence, not mocks

Mocks are allowed at process boundaries when the assertion concerns caller
behavior: timeout handling, abort propagation, retry limits, or provider error
mapping. They are not acceptable substitutes for representative fixtures in:

- scientific arrays, nodata, geometry, source-grid selection, distance, and
  quantile meaning;
- manifest/release schemas, checksums, provenance, and licence metadata;
- COG/PMTiles byte-range and corruption behavior;
- public-origin headers, cache, CORS, rollback, and zero-runtime-API journeys.

Those areas require a small checked-in representative fixture or an explicitly
tiered integration test. Large/raw source data stays outside Git.
