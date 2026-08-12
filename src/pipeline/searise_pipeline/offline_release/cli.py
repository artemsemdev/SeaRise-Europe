"""Command-line entry point for deterministic offline release builds."""

from __future__ import annotations

import os
from pathlib import Path

import click

from .model import StageFailure
from .runner import execute_profile_build


@click.command()
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option("--input-root", type=click.Path(path_type=Path), required=True)
@click.option("--code-revision", required=True)
@click.option("--release-date", required=True, help="Explicit YYYYMMDD release date.")
@click.option("--started-at", required=True, help="Explicit UTC receipt timestamp.")
@click.option("--completed-at", required=True, help="Explicit UTC receipt timestamp.")
@click.option(
    "--cache-dir",
    "cache_directory",
    type=click.Path(path_type=Path),
    required=True,
)
@click.option(
    "--output-dir",
    "output_directory",
    type=click.Path(path_type=Path),
    required=True,
)
@click.option(
    "--execution-receipt",
    "execution_receipt_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option(
    "--failure-receipt",
    "failure_receipt_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
def cli(
    profile_path: Path,
    input_root: Path,
    code_revision: str,
    release_date: str,
    started_at: str,
    completed_at: str,
    cache_directory: Path,
    output_directory: Path,
    execution_receipt_path: Path,
    failure_receipt_path: Path,
) -> None:
    """Build one immutable candidate without publishing or network access."""
    failure_receipt_preexisting = os.path.lexists(failure_receipt_path)
    try:
        result = execute_profile_build(
            profile_path=profile_path,
            input_root=input_root,
            code_revision=code_revision,
            release_date=release_date,
            started_at=started_at,
            completed_at=completed_at,
            cache_directory=cache_directory,
            output_directory=output_directory,
            execution_receipt_path=execution_receipt_path,
            failure_receipt_path=failure_receipt_path,
        )
    except StageFailure as exc:
        stage = exc.stage.value if exc.stage is not None else "preflight"
        receipt_status = (
            "failure receipt committed"
            if not failure_receipt_preexisting and os.path.lexists(failure_receipt_path)
            else "failure receipt not committed"
        )
        raise click.ClickException(
            f"offline build failed ({exc.code.value} at {stage}); {receipt_status}"
        ) from None
    click.echo(
        f"offline build complete: {result.execution_receipt['dataReleaseId']} "
        "(publication not attempted)"
    )


if __name__ == "__main__":
    cli()
