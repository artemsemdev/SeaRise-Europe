# SeaRise Europe documentation

The accepted main product is the coastal atlas. Engineering adoption is tracked
in [#490](https://github.com/artemsemdev/SeaRise-Europe/issues/490). The main route
uses the illustrative atlas fixture by default; the retained projection entry
is at `/projections/`.

| Question | Read |
| --- | --- |
| What are we building? | [Coastal atlas requirements](product/COASTAL_ATLAS_PRD.md), [design](product/COASTAL_ATLAS_DESIGN.md), [copy](product/COASTAL_ATLAS_CONTENT.md) |
| What changed architecturally? | [Atlas adoption decision](architecture/adr/ADR-028-coastal-atlas-adoption.md) |
| How do I run the atlas? | [Fixture and provisioned local quickstart](operations/coastal-atlas-development.md) |
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

The [development quickstart](operations/coastal-atlas-development.md) separates
fixture validation from the provisioned local source workflow. Neither implies
public delivery or scientific-release approval.
