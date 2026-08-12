"""CLI for candidate metadata validation, intentionally outside the signing boundary."""

from __future__ import annotations

from pathlib import Path

import click

from .validator import CandidateContractError, validate_candidate


@click.command(
    help=(
        "Validate only candidate JSON and its supported versioned inventory contract offline. "
        "It does not read or hash candidate artifact bytes, validate a candidate/evidence "
        "pair, sign, or approve production/publication."
    )
)
@click.option(
    "--candidate",
    "candidate_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
    help="Strict JSON candidate document to validate.",
)
def cli(candidate_path: Path) -> None:
    """Validate only candidate JSON and its checked-in versioned inventory offline."""
    try:
        summary = validate_candidate(candidate_path)
    except CandidateContractError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(
        f"candidate contract valid: {summary.candidate_id} "
        f"({summary.artifact_count} declared artifacts; publication not approved)"
    )
    click.echo(
        "Scope: does not read or hash candidate artifact bytes, validate the candidate/evidence "
        "pair, sign, or approve production/publication."
    )


if __name__ == "__main__":
    cli()
