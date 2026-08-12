"""Operator commands for the audited source registry."""

from __future__ import annotations

from pathlib import Path

import click

from .acquire import Acquirer, AcquisitionError
from .registry import RegistryError, load_registry, load_settlement_registry

DEFAULT_LOCK = Path(__file__).parents[2] / "sources" / "source-lock.json"
SETTLEMENT_LOCK_NAME = "source-lock.phase-1-settlements.json"
REPOSITORY_ROOT = Path(__file__).parents[4]
DEFAULT_CACHE = REPOSITORY_ROOT / "data" / "raw" / "sources"
DEFAULT_RECEIPTS = REPOSITORY_ROOT / "artifacts" / "acquisition-receipts"


def _registry(lock_path: Path):
    try:
        loader = (
            load_settlement_registry
            if lock_path.name == SETTLEMENT_LOCK_NAME
            else load_registry
        )
        return loader(lock_path)
    except RegistryError as exc:
        raise click.ClickException(str(exc)) from exc


def _run(
    operation: str,
    lock_path: Path,
    targets: tuple[str, ...],
    cache_dir: Path,
    receipts_dir: Path,
    attempts: int,
    backoff: float,
    timeout: float,
) -> None:
    registry = _registry(lock_path)
    acquirer = Acquirer(
        cache_dir,
        receipts_dir,
        attempts=attempts,
        backoff_seconds=backoff,
        timeout_seconds=timeout,
    )
    try:
        selected = registry.targets(targets)
        if not selected:
            raise click.ClickException("No acquisition targets were selected")
        for source, asset in selected:
            _, receipt = getattr(acquirer, operation)(source, asset)
            click.echo(receipt.to_json().rstrip())
    except (RegistryError, AcquisitionError) as exc:
        if isinstance(exc, AcquisitionError):
            click.echo(exc.receipt.to_json().rstrip(), err=True)
        raise click.ClickException(str(exc)) from exc


@click.group()
def cli() -> None:
    """Acquire only bytes pinned by the SeaRise Europe source lock."""


@cli.command("validate")
@click.option("--lock", "lock_path", type=click.Path(path_type=Path), default=DEFAULT_LOCK)
def validate_command(lock_path: Path) -> None:
    registry = _registry(lock_path)
    asset_count = sum(len(source.assets) for source in registry.sources)
    click.echo(f"Valid source lock: {len(registry.sources)} sources, {asset_count} assets")


@cli.command("publication-check")
@click.option("--lock", "lock_path", type=click.Path(path_type=Path), default=DEFAULT_LOCK)
def publication_check_command(lock_path: Path) -> None:
    issues = _registry(lock_path).publication_issues()
    if issues:
        raise click.ClickException("Publication blocked: " + "; ".join(issues))
    click.echo("Publication rights check passed for selected sources")


def _common_options(function):
    options = [
        click.option("--lock", "lock_path", type=click.Path(path_type=Path), default=DEFAULT_LOCK),
        click.option("--target", "targets", multiple=True, help="SOURCE or SOURCE:ASSET"),
        click.option("--cache-dir", type=click.Path(path_type=Path), default=DEFAULT_CACHE),
        click.option(
            "--receipts-dir",
            type=click.Path(path_type=Path),
            default=DEFAULT_RECEIPTS,
        ),
        click.option("--attempts", type=click.IntRange(min=1), default=3),
        click.option("--backoff", type=click.FloatRange(min=0), default=0.25),
        click.option("--timeout", type=click.FloatRange(min=0.1), default=30.0),
    ]
    for option in reversed(options):
        function = option(function)
    return function


@cli.command("fetch")
@_common_options
def fetch_command(**kwargs) -> None:
    """Fetch selected or explicitly targeted assets."""
    _run("fetch", **kwargs)


@cli.command("verify")
@_common_options
def verify_command(**kwargs) -> None:
    """Verify cached assets without network access."""
    _run("verify", **kwargs)
