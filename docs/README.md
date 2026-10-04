# SeaRise Europe documentation

The main product is the coastal atlas: `/` uses an illustrative fixture by
default, with explicit provisioned real-local and sealed private-demo workflows.
The retained AR6 projection reference is at `/projections/`.

Source code, executable contracts and tests are the primary implementation
reference. The [architecture README](architecture/README.md) indexes all 16
topic views, their source anchors, decisions and the diagram; it distinguishes
implemented behavior from future delivery work.

| Question | Read |
| --- | --- |
| What is in the demo prerelease? | [v0.1.0-rc.1 contents, verification, limitations and rollback](releases/v0.1.0-rc.1.md) |
| What are we building? | [Coastal atlas requirements](product/COASTAL_ATLAS_PRD.md), [design](product/COASTAL_ATLAS_DESIGN.md), [copy](product/COASTAL_ATLAS_CONTENT.md) |
| What changed architecturally? | [Atlas adoption decision](architecture/adr/ADR-028-coastal-atlas-adoption.md) |
| How do I run the atlas? | [Fixture and provisioned local quickstart](operations/coastal-atlas-development.md) |
| How do I prepare a local demo candidate? | [Candidate preparation, demonstration and rollback](operations/local-demo-candidate.md) |
| How do I contribute today? | [Contributor commands](../CONTRIBUTING.md), [testing](testing/README.md) |
| What is implemented? | [Architecture overview](architecture/README.md); guides change with each implementation PR |
| What remains? | [Current risks and open decisions](architecture/12-risks-assumptions-and-open-questions.md), [scoped backlog](delivery/coastal-atlas-backlog.md); public hosting is separate work |

## Scoped reference and history

- [AR6 requirements](product/PRD.md),
  [copy](product/CONTENT_GUIDELINES.md), and
  [vision](product/VISION.md) describe the retained projection app.
- [Projection methodology](methodology.md) and
  [ADR-024](architecture/adr/ADR-024-ar6-regional-projection-contract.md) preserve
  the retained relative-level contract. They are not the atlas depth methodology.
- The [Flight design](product/Mock/DESIGN.md) is scoped to that reference app.
- Existing scientific evidence, receipts, and past decisions keep their original
  paths and outcomes. The [earlier delivery roadmap](delivery/README.md) records
  completed static migration and subsequent hosting work; it does not replace #490.

The [development quickstart](operations/coastal-atlas-development.md) separates
fixture validation from the provisioned local source workflow. Neither implies
public delivery or scientific-release approval.
