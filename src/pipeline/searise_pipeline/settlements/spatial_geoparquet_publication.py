"""Immutable publication of one receipt-bound settlement GeoParquet artifact."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from . import full_source_stage as source_stage
from . import spatial_asset_authority as authority
from . import spatial_classification_stage as spatial_stage
from . import spatial_geoparquet as geoparquet
from . import spatial_stage_runner as publication


class SpatialGeoParquetPublicationError(ValueError):
    """A GeoParquet artifact and its receipt could not be published exactly."""


_CREATE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | authority._NOFOLLOW_FLAGS
_FALSE_CLAIMS = (
    "productionClaim",
    "publicationClaim",
    "canonicalGeometryClaim",
    "hazardExtentClaim",
    "scientificApprovalClaim",
    "ownerApprovalClaim",
    "signingClaim",
)
_ENVELOPE_FALSE_CLAIMS = ("canonicalGeometryClaim", "hazardExtentClaim", "scientificApprovalClaim", "ownerApprovalClaim")  # noqa: E501  # fmt: skip


def _canonical(value: object) -> bytes:
    try:
        return source_stage._canonical_json(value).encode("utf-8")
    except (ValueError, UnicodeEncodeError) as exc:
        raise SpatialGeoParquetPublicationError("publication receipt is not canonical") from exc


def _stream(asset: Any, mode: str) -> BinaryIO:
    try:
        return os.fdopen(os.dup(asset.descriptor), mode)
    except OSError as exc:
        raise SpatialGeoParquetPublicationError(f"cannot read {asset.label}: {exc}") from exc


def _serialize_owned(
    directory: Any,
    name: str,
    database: Path,
    spatial_receipt: Path,
    release_id: str,
    work_dir: Path,
    owned: list[tuple],
) -> geoparquet.SpatialGeoParquetEvidence:
    descriptor = -1
    primary: BaseException | None = None
    try:
        descriptor = os.open(name, _CREATE_FLAGS, 0o600, dir_fd=directory.descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SpatialGeoParquetPublicationError("staged GeoParquet is not a regular file")
        owned.append((name, metadata.st_dev, metadata.st_ino))
        with os.fdopen(descriptor, "w+b", closefd=False) as stream:
            evidence = geoparquet.serialize_spatial_geoparquet(
                database,
                spatial_receipt,
                stream,
                data_release_id=release_id,
                work_dir=work_dir,
            )
            stream.flush()
        os.fsync(descriptor)
        return evidence
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if descriptor >= 0:
            authority._close(descriptor, primary)


def _validate_artifact(
    asset: Any, database: Path, receipt: Path, work_dir: Path
) -> geoparquet.SpatialGeoParquetEvidence:
    with _stream(asset, "rb") as stream:
        stream.seek(0)
        try:
            return geoparquet.validate_spatial_geoparquet(
                stream, database, receipt, work_dir=work_dir
            )
        finally:
            stream.seek(0)


def _assert_owned(asset: Any, record: tuple) -> None:
    if (asset.name, asset.device, asset.inode) != record:
        raise SpatialGeoParquetPublicationError(f"staged {asset.label} identity changed")


def _receipt_document(
    release_id: str,
    source_database: Any,
    source_receipt: Any,
    spatial_identity: Any,
    artifact: Any,
    evidence: geoparquet.SpatialGeoParquetEvidence,
    rebuild: geoparquet.SpatialGeoParquetEvidence,
) -> dict[str, Any]:
    envelope = evidence.artifact_envelope
    if (
        evidence != rebuild
        or evidence.parquet_sha256 != artifact.sha256
        or evidence.spatial_receipt_sha256 != source_receipt.sha256
        or spatial_identity.receipt_sha256 != source_receipt.sha256
        or evidence.spatial_candidate_identity != spatial_identity.candidate_identity
        or envelope.get("dataReleaseId") != release_id
        or envelope.get("mediaType") != "application/vnd.apache.parquet"
        or envelope.get("formatVersion") != "1.1.0"
        or envelope.get("publicationEligible") is not False
        or any(envelope.get(name) is not False for name in _ENVELOPE_FALSE_CLAIMS)
    ):
        raise SpatialGeoParquetPublicationError(
            "GeoParquet serialization or rebuild evidence differs from its authority"
        )
    document: dict[str, Any] = {
        "schemaVersion": 1,
        "materializationPerformed": True,
        "publicationEligible": False,
        **{name: False for name in _FALSE_CLAIMS},
        "dataReleaseId": release_id,
        "source": {
            "spatialDatabaseSha256": source_database.sha256,
            "spatialReceiptSha256": source_receipt.sha256,
            "spatialReceiptDeterministicIdentity": spatial_identity.receipt_identity,
            "spatialCandidateDeterministicIdentity": spatial_identity.candidate_identity,
        },
        "artifact": {
            "mediaType": envelope["mediaType"],
            "formatVersion": envelope["formatVersion"],
            "byteSize": artifact.size,
            "sha256": artifact.sha256,
            "rowCount": evidence.row_count,
            "sourceRowsSha256": evidence.source_rows_sha256,
            "logicalRowsSha256": evidence.logical_rows_sha256,
            "artifactEnvelopeSha256": hashlib.sha256(_canonical(envelope)).hexdigest(),
        },
        "rebuild": {
            "performed": True,
            "byteForByteMatch": True,
            "sha256": rebuild.parquet_sha256,
            "serializer": "searise-settlement-geoparquet-v1",
            "validationProtocol": "staged-and-published-descriptor-v1",
        },
    }
    document["deterministicIdentity"] = hashlib.sha256(_canonical(document) + b"\n").hexdigest()
    return document


def _receipt_bytes(document: dict[str, Any]) -> bytes:
    return _canonical(document) + b"\n"


def _validate_receipt(asset: Any, expected: dict[str, Any]) -> None:
    with _stream(asset, "rb") as stream:
        stream.seek(0)
        raw = stream.read()
        stream.seek(0)
    if raw != _receipt_bytes(expected):
        raise SpatialGeoParquetPublicationError("GeoParquet publication receipt differs")


def _diagnose_retained_directory(
    parent: Any, name: str, private: Any, cleanup: BaseException
) -> BaseException:
    try:
        current = authority._path_stat(parent.descriptor, name)
    except BaseException:
        return cleanup
    if stat.S_ISDIR(current.st_mode) and authority._identity(current) == (
        private.device,
        private.inode,
    ):
        return SpatialGeoParquetPublicationError(
            f"retained GeoParquet staging directory {name}: {cleanup}"
        )
    return cleanup


def _build_private(
    database: Path,
    spatial_receipt: Path,
    output: Path,
    receipt_path: Path,
    release_id: str,
    work_dir: Path,
    output_directory: Any,
    private: Any,
    owned: list[tuple],
) -> dict[str, Any]:
    promoted: list[tuple[str, Any]] = []
    try:
        with ExitStack() as stack:
            source_root, sources = stack.enter_context(
                spatial_stage._validation_snapshots(
                    {"spatial.duckdb": database, "spatial-receipt.json": spatial_receipt},
                    work_dir,
                )
            )
            database = source_root / "spatial.duckdb"
            spatial_receipt = source_root / "spatial-receipt.json"
            spatial_identity = geoparquet._receipt(
                spatial_stage._read_asset(sources["spatial-receipt.json"])
            )
            evidence = _serialize_owned(
                private, output.name, database, spatial_receipt, release_id, work_dir, owned
            )
            artifact_record = owned[-1]
            rebuild_name = ".deterministic-rebuild.parquet"
            rebuild = _serialize_owned(
                private, rebuild_name, database, spatial_receipt, release_id, work_dir, owned
            )
            rebuild_record = owned[-1]
            artifact = stack.enter_context(
                authority._open_asset(private, PurePosixPath(output.name), "GeoParquet artifact")
            )
            rebuild_asset = stack.enter_context(
                authority._open_asset(private, PurePosixPath(rebuild_name), "GeoParquet rebuild")
            )
            _assert_owned(artifact, artifact_record)
            _assert_owned(rebuild_asset, rebuild_record)
            publication._fsync_asset(artifact)
            publication._fsync_asset(rebuild_asset)
            if artifact.sha256 != rebuild_asset.sha256 or artifact.size != rebuild_asset.size:
                raise SpatialGeoParquetPublicationError("GeoParquet rebuild bytes differ")
            staged = _validate_artifact(artifact, database, spatial_receipt, work_dir)
            if staged != evidence:
                raise SpatialGeoParquetPublicationError("staged GeoParquet evidence differs")
            document = _receipt_document(
                release_id,
                sources["spatial.duckdb"],
                sources["spatial-receipt.json"],
                spatial_identity,
                artifact,
                evidence,
                rebuild,
            )
            publication._write_owned(private, receipt_path.name, _receipt_bytes(document), owned)
            receipt_record = owned[-1]
            receipt_asset = stack.enter_context(
                authority._open_asset(
                    private, PurePosixPath(receipt_path.name), "GeoParquet publication receipt"
                )
            )
            _assert_owned(receipt_asset, receipt_record)
            _validate_receipt(receipt_asset, document)
            publication._fsync_directory(private)
            authority._assert_directory(output_directory)
            publication._link_no_overwrite(private, output.name, output_directory)
            promoted.append((output.name, artifact))
            publication._fsync_directory(output_directory)
            publication._assert_binding(output_directory, output.name, artifact)
            publication._link_no_overwrite(private, receipt_path.name, output_directory)
            promoted.append((receipt_path.name, receipt_asset))
            publication._fsync_directory(output_directory)
            publication._assert_binding(output_directory, output.name, artifact)
            publication._assert_binding(output_directory, receipt_path.name, receipt_asset)
            published = _validate_artifact(artifact, database, spatial_receipt, work_dir)
            if published != evidence:
                raise SpatialGeoParquetPublicationError("published GeoParquet evidence differs")
            _validate_receipt(receipt_asset, document)
            publication._assert_binding(output_directory, output.name, artifact)
            publication._assert_binding(output_directory, receipt_path.name, receipt_asset)
            authority._assert_directory(output_directory)
            return document
    except BaseException as primary:
        if promoted:
            publication._rollback_publication(primary, output_directory, private, promoted)
        raise


def build_spatial_geoparquet(
    spatial_database: Path,
    spatial_receipt: Path,
    output: Path,
    receipt_path: Path,
    *,
    data_release_id: str,
    work_dir: Path,
) -> dict[str, Any]:
    """Serialize, rebuild, validate, and immutably publish one GeoParquet pair."""
    try:
        with ExitStack() as stack:
            output_parent = stack.enter_context(
                authority._open_directory_path(output.parent, "GeoParquet output directory")
            )
            receipt_parent = stack.enter_context(
                authority._open_directory_path(receipt_path.parent, "GeoParquet receipt directory")
            )
            authority._assert_secure_work_directory(output_parent)
            if output.name == receipt_path.name or (output_parent.device, output_parent.inode) != (
                receipt_parent.device,
                receipt_parent.inode,
            ):
                raise SpatialGeoParquetPublicationError(
                    "GeoParquet artifact and receipt need distinct paths in one directory"
                )
            if not publication._absent(output_parent, output.name) or not publication._absent(
                output_parent, receipt_path.name
            ):
                raise SpatialGeoParquetPublicationError(
                    "GeoParquet output exists; overwrite refused"
                )
            published_root = authority._descriptor_path(output_parent)
            output, receipt_path = published_root / output.name, published_root / receipt_path.name
            private_name, private = authority._create_private(output_parent)
            authority._stack_close(stack, private.descriptor)
            owned: list[tuple] = []
            primary: BaseException | None = None
            try:
                return _build_private(
                    spatial_database,
                    spatial_receipt,
                    output,
                    receipt_path,
                    data_release_id,
                    work_dir,
                    output_parent,
                    private,
                    owned,
                )
            except BaseException as exc:
                primary = exc
                raise
            finally:
                try:
                    authority._remove_private(
                        output_parent, private_name, private, tuple(owned), ()
                    )
                except BaseException as cleanup:
                    diagnosed = _diagnose_retained_directory(
                        output_parent, private_name, private, cleanup
                    )
                    if primary is None:
                        if diagnosed is cleanup:
                            raise
                        raise diagnosed from cleanup
                    authority._note_cleanup(primary, diagnosed)
    except SpatialGeoParquetPublicationError:
        raise
    except Exception as exc:
        raise SpatialGeoParquetPublicationError(f"GeoParquet publication failed: {exc}") from exc
