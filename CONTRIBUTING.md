# Contributing

## Scope

This repository is currently documentation-first. The main contribution types are:

- product clarifications
- architecture improvements
- requirement traceability fixes
- repo hygiene for a public GitHub project

If you want to propose a large structural change, open an issue or discussion first so scope and direction are clear before drafting a pull request.

## Working Rules

- Keep `docs/product/` and `docs/architecture/` aligned.
- When changing architecture decisions, reference the relevant PRD requirement IDs where possible.
- Make assumptions explicit instead of burying them in prose.
- Prefer focused pull requests over mixed, unrelated edits.
- Do not commit secrets, local env files, generated datasets, build outputs, or Claude local state.

## Documentation Conventions

- Preserve the existing document numbering and file naming in `docs/architecture/`.
- Use clear, direct language.
- Update metadata, status, or version fields when the document meaningfully changes.
- Keep "confirmed" product decisions distinct from "proposed" architecture decisions.

## Pull Requests

Include:

- a short summary of what changed
- why the change is needed
- links to the related issue, discussion, or document section when relevant

Before submitting, check that:

- the change does not contradict the PRD or vision docs
- any new open questions are tracked explicitly
- the repo still contains no secrets or generated artifacts

## Code Contributions

Implementation code does not exist in this repository yet. If code is introduced later, contribution expectations can be expanded to include tests, linting, and local setup instructions.
