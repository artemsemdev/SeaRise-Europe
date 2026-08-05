# Phase 0.10 geoid evaluator disposition

Issue [#94](https://github.com/artemsemdev/SeaRise-Europe/issues/94) has a
terminal **blocked** disposition. The production evaluator identity and all
known numerical conventions are pinned, but the evaluator is not approved for
scientific publication.

The machine-readable decision is
[`geoid-evaluator.json`](../../src/pipeline/science/geoid-evaluator.json). The
comparison packet is
[`geoid-evaluator-validation.json`](../../src/pipeline/science/evidence/geoid-evaluator-validation.json).
Their JSON Schemas reject missing or changed identities, constants,
conventions, comparisons, review evidence, and gate state.

## Pinned production path

- Engine: SHTOOLS/pyshtools 4.13.1, tag commit
  `4c7fd73fd61f863351fdc067294c8538acc70d89`, BSD-3-Clause.
- Binary installation: `--no-deps --only-binary=:all: --require-hashes` from
  the checked-in wheel lock. The execution environment remains separately
  receipted because the native wheel and its numerical dependencies are part
  of the reproducibility claim.
- Inputs: WGS84 geodetic latitude/longitude at zero ellipsoidal height;
  longitude is east-positive and normalized modulo 360.
- Synthesis: WGS84 geodetic coordinates are converted to geocentric latitude
  and radius before direct point synthesis. Coefficients use fully normalized
  geodesy 4π normalization, no Condon–Shortley phase, degree-major/order-major
  cosine-then-sine ordering, and no interpolation or extrapolation.
- GOCO06S: degree/order 300, `GM=398600441500000.0 m³/s²`,
  `R=6378136.3 m`, evaluated at 2010-01-01 as
  `gfct + acos` (trend and sine terms are zero at the reference epoch).
  Its zero-tide C20 is converted to tide-free with
  `C20_tide_free = C20_zero_tide + 4.1736e-9` from IERS Conventions 2010.
- EGM2008: degree 2190/order 2159, the same model GM and radius, tide-free,
  static-model epoch marked not applicable, NGA `-0.41 m` zero-degree term,
  and the NGA degree-2160 height-anomaly-to-geoid correction.
- Non-finite coordinates or coefficients, missing coefficients, nodata, a
  model identity mismatch, or a convention mismatch stop the computation.

## Numerical evidence

Six expected EGM2008 geoid undulations from the official NGA release were
evaluated independently by the pinned SHTOOLS path. The vectors exercise both
signs, both hemispheres, longitude wrapping, a harmonic-grid boundary, and both
poles. The maximum absolute disagreement is `0.005301211346 m`, below the
predeclared `0.01 m` tolerance.

Six GOCO06S vectors cover European coasts, islands, longitude wrapping, the
Baltic, Adriatic, Black Sea, Atlantic, and North Sea contexts. The pinned
evaluator produced finite values, but the independent ICGEM job result endpoint
repeatedly returned HTTP 502 after the job reached `Done`. No independent
expected values were copied or inferred. Therefore the comparison remains
blocked and the partial EGM2008 disagreement must not be promoted into a total
evaluator bound.

## Remaining approval conditions

Publication remains blocked until all of the following are recorded:

1. independent GOCO06S point results pass the predeclared `0.01 m` tolerance,
   or the methodology is explicitly rejected;
2. the pinned Darwin and Linux environments reproduce within `1e-9 m`;
3. an independent scientific or geodetic reviewer records an explicit
   approved, rejected, or blocked disposition; and
4. the approved evaluator policy and disagreement bound are bound into the
   vertical transformation receipt.

The fail-closed uncertainty adapter emits `bound_m=None` while the evidence is
blocked. CI success cannot change the scientific disposition and cannot replace
independent review.

## Source record

- NGA EGM2008 archive:
  <https://earth-info.nga.mil/php/download.php?file=egm-08spherical>
- GOCO06S coefficient archive:
  <https://icgem.gfz.de/getmodel/zip/32ec2884630a02670476f752d2a2bf1c395d8c8d6d768090ed95b4f04b0d5863/GOCO06s.zip>
- ICGEM independent calculation receipt:
  <https://icgem.gfz.de/calc_stat/7de41c2ce7745dbf10bb6ce6fc1e66a558e57c19f3093a3a641dc0e631fd9efa>
- IERS Conventions 2010, chapter 6:
  <https://www.iers.org/SharedDocs/Publikationen/EN/IERS/Publications/tn/TechnNote36/tn36_079.pdf>
