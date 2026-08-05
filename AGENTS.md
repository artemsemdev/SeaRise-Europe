# Contribution Guidelines

## Preserve User Attribution

All changes and commits must be made solely in the user's name, using the user's existing Git identity.

- Do not change or override the configured Git author or committer identity.
- Do not attribute changes or commits to Codex, OpenAI, an AI assistant, or another person.
- Do not add AI attribution or `Co-authored-by` trailers to commit messages or pull requests.

## Work Through Small Pull Requests

Keep pull requests focused on one coherent change.

Bad pull request:

> Implemented everything.

Good pull requests include:

- Add transcription job model
- Add ffmpeg service abstraction
- Add basic file import screen
- Add export to TXT
- Add CI pipeline
- Add architecture overview

Size guidance:

- Good: 100–400 lines changed.
- Acceptable: up to 800 lines changed when the change is mechanical.
- Bad: a huge pull request mixing architecture, UI, tests, refactoring, and documentation.

Use this pull request template:

```markdown
## Summary

What was changed?

## Why

Why is this change needed?

## Testing

How was it tested?

## Screenshots

Add screenshots or GIFs if UI changed.

## Checklist

- [ ] Tests added or updated
- [ ] Documentation updated if needed
- [ ] CI passes
- [ ] No secrets or local-only files committed
```

## Coordinate Multiple Issues with Integration Branches

Use the simplest branch topology that preserves independent review and a green
default branch.

- For one issue, or several truly independent issues, create one issue branch
  and one pull request per issue directly against `master`.
- For a phase, epic, or ordered set of dependent issues, create one temporary
  integration branch from the latest `origin/master`, for example
  `integration/phase-1`.
- Create every issue branch from the commit it actually depends on. Normally
  this is the current integration branch, using a name such as
  `agent/issue-123-short-description`.
- Open each issue pull request against the integration branch, not `master`.
  Keep the issue PR focused, independently reviewable, and linked to its issue.
- Merge issue PRs into the integration branch one at a time in dependency
  order, only after their required checks pass. Update the integration branch
  before starting the next dependent issue.
- After all issue PRs are integrated, run the complete phase-level validation
  and open one final pull request from the integration branch to `master`.
- Do not merge the final integration pull request into `master` unless the user
  explicitly requests it. Delete temporary issue and integration branches only
  after the final merge and verification.

Parallel agents may work only on issues whose contracts and files do not depend
on unfinished sibling work. Give every agent its own Git worktree and issue
branch. Never let multiple agents commit to the same branch or worktree.

Before integrating parallel work:

1. Decide and record the dependency order.
2. Refresh the issue branch from the latest integration branch.
3. Resolve conflicts and rerun tests on the issue branch, not on `master`.
4. Merge the issue pull request into the integration branch after CI passes.
5. Refresh the remaining dependent branches before continuing.

Prefer rebasing unpublished or agent-owned issue branches to keep their history
linear. Do not rewrite a shared or reviewed branch without coordination; use a
normal merge when preserving published history is safer. Never force-push
without `--force-with-lease` and explicit confirmation that nobody else is
using the branch.

The integration branch is temporary coordination infrastructure, not a place
for unrelated cleanup or direct implementation commits. If an integration fix
is required, make it through its own focused branch and pull request.

## Create Atomic, Readable Commits

Plan commit boundaries before staging changes. Each commit should represent one
clear intent that a reviewer can understand, test, and revert independently.

- Keep commits small and cohesive. Prefer roughly 100–400 changed lines and a
  small number of related files when the natural boundary allows it.
- Split contracts/models, implementation, tests, documentation, and CI into
  separate commits when each part can remain valid and reviewable on its own.
- Keep behavior-defining tests with the implementation when separating them
  would leave a broken, unverified, or misleading intermediate commit.
- Every commit must leave the repository buildable and its relevant tests
  passing. Do not split work only to satisfy a line or file-count target.
- Stage explicit paths or hunks. Review both `git diff --cached` and
  `git diff --cached --stat` before committing; do not blindly stage the entire
  worktree.
- Do not publish `WIP`, cleanup, or fixup commits. Reshape local history into
  the intended logical sequence before pushing when it is safe to do so.
- Use a focused Conventional Commit message for every commit so the sequence
  explains how the change was built.

For example, a source-acquisition change should be split into a readable
sequence such as:

```text
feat(pipeline): add audited source lock contracts
feat(pipeline): add verified acquisition engine
test(pipeline): cover acquisition and cache failures
docs(pipeline): document source acquisition operations
ci(pipeline): validate source registry
```

Larger commits are acceptable only when the change is genuinely indivisible or
mechanical. Explain that exception in the pull request instead of silently
combining unrelated work.

## Use Conventional Commits

Use Conventional Commits so the history remains understandable and can support automated changelogs and releases.

Format:

```text
<type>[optional scope]: <description>
```

Examples:

```text
feat: add audio file import
fix: handle missing ffmpeg binary
docs: add architecture overview
test: add transcription job unit tests
refactor: extract whisper service interface
ci: add GitHub Actions build pipeline
chore: update dependencies
```

Recommended types:

- `feat`: new feature
- `fix`: bug fix
- `docs`: documentation only
- `refactor`: code change without behavior change
- `test`: tests
- `ci`: CI pipeline changes
- `build`: build system or dependencies
- `chore`: maintenance
- `perf`: performance improvement
- `style`: formatting only

Mark a breaking change in the type:

```text
feat!: change transcript export API
```

Or add a breaking-change footer:

```text
feat: change transcript export API

BREAKING CHANGE: The export service now requires an explicit output format.
```

## Maintain a Human-Readable Changelog

Keep the root `CHANGELOG.md` useful to users, contributors, and the project
owner. It is a curated product history, not a copy of `git log`.

- Keep `## [Unreleased]` at the top and update it in the same pull request as a
  notable feature, behavior or contract change, methodology decision,
  deprecation, removal, important fix, or security improvement.
- Use only the categories that have entries: `Added`, `Changed`, `Deprecated`,
  `Removed`, `Fixed`, and `Security`.
- Describe outcomes and impact in plain language. Combine related commits into
  one meaningful entry and omit refactors, formatting, typo fixes, and other
  changes that do not matter outside their implementation.
- Do not generate the changelog by dumping commit subjects. Conventional
  Commits support history and automation, but they do not replace editorial
  release notes.
- When cutting a release, move the applicable entries from `Unreleased` into a
  dated `## [MAJOR.MINOR.PATCH] - YYYY-MM-DD` section and leave a fresh
  `Unreleased` section for subsequent work.

## Create Versioned Releases

Create the first release as `v0.1.0` only when the MVP definition of done and
its release checks pass. Continue with Semantic Versioning using tags in the
form `vMAJOR.MINOR.PATCH`:

- `PATCH` for backward-compatible bug fixes that do not intentionally change
  public contracts.
- `MINOR` for backward-compatible features.
- `MAJOR` for breaking public contract or behavior changes.

Before publishing a GitHub Release:

- merge the release scope to the default branch and require green CI;
- finalize and commit the dated changelog section;
- tag the exact reviewed commit with the intended SemVer version;
- write human-readable release notes organized by impact, normally `Added`,
  `Changed`, `Fixed`, and `Known limitations`;
- include artifact, integrity, migration, and rollback information when it is
  relevant;
- do not present a scientifically blocked, synthetic-only, or incomplete build
  as the MVP release.

Release notes must explain the deliverable and its limitations rather than
listing every merged pull request.
