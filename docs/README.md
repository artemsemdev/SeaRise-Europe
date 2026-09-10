# SeaRise Europe documentation

The accepted main product is the coastal atlas. Engineering adoption is tracked
in [#490](https://github.com/artemsemdev/SeaRise-Europe/issues/490); the integration
branch still uses the projection entry until the primary-app slice lands.

| Question | Read |
| --- | --- |
| What are we building? | [Coastal atlas requirements](product/COASTAL_ATLAS_PRD.md), [design](product/COASTAL_ATLAS_DESIGN.md), [copy](product/COASTAL_ATLAS_CONTENT.md) |
| What changed architecturally? | [Atlas adoption decision](architecture/adr/ADR-028-coastal-atlas-adoption.md) |
| How do I contribute today? | [Contributor commands](../CONTRIBUTING.md), [testing](testing/README.md) |
| What is implemented? | [Architecture overview](architecture/README.md); guides change with each implementation PR |
| What remains? | [Atlas adoption epic](https://github.com/artemsemdev/SeaRise-Europe/issues/490); public hosting is a later workstream |

## Scoped reference and history

- [AR6 requirements](product/PRD.md),
  [copy](product/CONTENT_GUIDELINES.md), and
  [vision](product/VISION.md) describe the retained projection app.
- [Projection methodology](methodology.md) and
  [ADR-024](architecture/adr/ADR-024-ar6-regional-projection-contract.md) preserve
  the published relative-level contract. They are not the atlas depth methodology.
- The [Flight design](product/Mock/DESIGN.md) is scoped to that reference app.
- Existing scientific evidence, receipts, and past decisions keep their original
  paths and outcomes. The [earlier delivery roadmap](delivery/README.md) records
  completed static migration and subsequent hosting work; it does not replace #490.

Local atlas startup/data documentation arrives with the corresponding runtime
slice. Do not use this target definition as evidence that the current normal
build already includes the accepted map.
