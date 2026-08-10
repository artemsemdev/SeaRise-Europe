from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Optional, cast

import pytest

from searise_pipeline.offline_release import cog_range as cog_range_module
from searise_pipeline.offline_release import projection_bundle as projection_bundle_module
from searise_pipeline.offline_release.cog_range import (
    CogArtifactIdentity,
    RangeResponse,
    load_reviewed_cog_identities,
    validate_reviewed_cog_range_access,
)
from searise_pipeline.science import ScienceContractError

REPOSITORY_ROOT = Path(__file__).parents[4]
FIXTURE_ROOT = (
    REPOSITORY_ROOT / "contracts/release/v1/fixtures/release/"
    "searise-europe-v1.0.0-20260810-c096aeab4e09"
)
Mutation = Callable[[CogArtifactIdentity, int, int, RangeResponse], object]


class LocalRangeTransport:
    """Deterministic fixture transport; it is not public delivery evidence."""

    def __init__(self, root: Path, mutation: Optional[Mutation] = None) -> None:
        self.root = root
        self.mutation = mutation
        self.calls: list[tuple[str, int, int]] = []

    def get_range(
        self,
        artifact: CogArtifactIdentity,
        *,
        start: int,
        end: int,
    ) -> RangeResponse:
        self.calls.append((artifact.path, start, end))
        data = (self.root / artifact.path).read_bytes()
        actual_end = min(end, len(data) - 1)
        response = RangeResponse(
            status=206,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{actual_end}/{len(data)}",
                "Content-Length": str(actual_end - start + 1),
            },
            body=data[start : actual_end + 1],
        )
        if self.mutation is not None and len(self.calls) == 1:
            return cast(RangeResponse, self.mutation(artifact, start, end, response))
        return response


def _replace(
    response: RangeResponse,
    *,
    status: Optional[int] = None,
    headers: Optional[dict[str, str]] = None,
    body: Optional[bytes] = None,
) -> RangeResponse:
    return RangeResponse(
        status=response.status if status is None else status,
        headers=response.headers if headers is None else headers,
        body=response.body if body is None else body,
    )


def test_validates_exact_nine_cogs_and_reader_driven_ranges() -> None:
    identities = load_reviewed_cog_identities(REPOSITORY_ROOT)
    transport = LocalRangeTransport(FIXTURE_ROOT)

    report = validate_reviewed_cog_range_access(
        FIXTURE_ROOT,
        repository_root=REPOSITORY_ROOT,
        transport=transport,
    )

    assert len(identities) == 9
    assert report["artifactCount"] == 9
    assert report["evidenceDisposition"] == "fixture-validation-only"
    assert {item["path"] for item in report["artifacts"]} == {
        identity.path for identity in identities
    }
    assert all(
        item["canonicalProbes"] == ["beginning", "middle", "end"] for item in report["artifacts"]
    )
    assert all(item["readerRangeRequests"] == 3 for item in report["artifacts"])
    assert report["rangeRequestCount"] == len(transport.calls) == 54
    assert sum(start == 0 and end == 65535 for _, start, end in transport.calls) == 9
    assert all(
        (FIXTURE_ROOT / identity.path).stat().st_size == identity.byte_size
        for identity in identities
    )
    for item in report["artifacts"]:
        size = item["byteSize"]
        middle = size // 2 - 32
        assert item["requestCoordinates"] == [
            ["beginning", 0, 63, 63],
            ["middle", middle, middle + 63, middle + 63],
            ["end", size - 64, size - 1, size - 1],
            ["reader-browser", 0, 65535, size - 1],
            ["reader-ifd-count", 192, 193, 193],
            ["reader-ifd-payload", 194, 449, 449],
        ]


@pytest.mark.parametrize(
    ("case", "mutation"),
    [
        (
            "range ignored",
            lambda artifact, start, end, response: _replace(response, status=200),
        ),
        (
            "malformed status",
            lambda artifact, start, end, response: RangeResponse(
                status=True, headers=response.headers, body=response.body
            ),
        ),
        (
            "malformed Content-Range",
            lambda artifact, start, end, response: _replace(
                response,
                headers={**response.headers, "Content-Range": "bytes malformed"},
            ),
        ),
        (
            "wrong Content-Range total",
            lambda artifact, start, end, response: _replace(
                response,
                headers={
                    **response.headers,
                    "Content-Range": (
                        f"bytes {start}-{start + len(response.body) - 1}/{artifact.byte_size + 1}"
                    ),
                },
            ),
        ),
        (
            "missing Content-Length",
            lambda artifact, start, end, response: _replace(
                response,
                headers={
                    key: value for key, value in response.headers.items() if key != "Content-Length"
                },
            ),
        ),
        (
            "malformed Content-Length",
            lambda artifact, start, end, response: _replace(
                response,
                headers={**response.headers, "Content-Length": f"+{len(response.body)}"},
            ),
        ),
        (
            "full-body substitution",
            lambda artifact, start, end, response: _replace(
                response,
                headers={**response.headers, "Content-Length": str(artifact.byte_size)},
                body=(FIXTURE_ROOT / artifact.path).read_bytes(),
            ),
        ),
        (
            "truncated body",
            lambda artifact, start, end, response: _replace(response, body=response.body[:-1]),
        ),
        (
            "corrupted body",
            lambda artifact, start, end, response: _replace(
                response,
                body=bytes([response.body[0] ^ 1]) + response.body[1:],
            ),
        ),
        (
            "range support missing",
            lambda artifact, start, end, response: _replace(
                response,
                headers={**response.headers, "Accept-Ranges": "none"},
            ),
        ),
        ("wrong response object", lambda artifact, start, end, response: {}),
        (
            "wrong headers type",
            lambda artifact, start, end, response: RangeResponse(206, [], response.body),
        ),
        (
            "wrong body type",
            lambda artifact, start, end, response: RangeResponse(
                206, response.headers, bytearray(response.body)
            ),
        ),
        (
            "wrong header key type",
            lambda artifact, start, end, response: RangeResponse(206, {1: "bytes"}, response.body),
        ),
        (
            "wrong header value type",
            lambda artifact, start, end, response: RangeResponse(
                206, {"Accept-Ranges": 1}, response.body
            ),
        ),
    ],
)
def test_rejects_malformed_or_corrupt_range_responses(
    case: str,
    mutation: Mutation,
) -> None:
    transport = LocalRangeTransport(FIXTURE_ROOT, mutation)

    with pytest.raises(ScienceContractError, match="COG"):
        validate_reviewed_cog_range_access(
            FIXTURE_ROOT,
            repository_root=REPOSITORY_ROOT,
            transport=transport,
        )

    assert case
    assert len(transport.calls) == 1


def test_rejects_local_artifact_identity_mismatch_before_transport(tmp_path: Path) -> None:
    fixture_copy = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT / "analysis", fixture_copy / "analysis")
    identities = load_reviewed_cog_identities(REPOSITORY_ROOT)
    changed = fixture_copy / identities[0].path
    changed.write_bytes(changed.read_bytes() + b"corruption")
    transport = LocalRangeTransport(fixture_copy)

    with pytest.raises(ScienceContractError, match="reviewed identity"):
        validate_reviewed_cog_range_access(
            fixture_copy,
            repository_root=REPOSITORY_ROOT,
            transport=transport,
        )

    assert transport.calls == []


def test_rejects_same_length_artifact_corruption_before_transport(tmp_path: Path) -> None:
    fixture_copy = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT / "analysis", fixture_copy / "analysis")
    identity = load_reviewed_cog_identities(REPOSITORY_ROOT)[0]
    changed = fixture_copy / identity.path
    data = bytearray(changed.read_bytes())
    data[-1] ^= 1
    changed.write_bytes(data)
    transport = LocalRangeTransport(fixture_copy)

    with pytest.raises(ScienceContractError, match="reviewed identity"):
        validate_reviewed_cog_range_access(
            fixture_copy, repository_root=REPOSITORY_ROOT, transport=transport
        )
    assert transport.calls == []


@pytest.mark.parametrize(
    ("name", "field", "value"),
    [
        ("final-gate.json", ("issue",), 51),
        ("final-gate.json", ("automatedValidation",), "failed"),
        ("final-gate.json", ("blockingChecks",), ["failure"]),
        ("final-gate.json", ("ownerDecision",), "pending"),
        ("final-gate.json", ("releaseDisposition",), "rejected"),
        ("final-gate.json", ("phase1Unlocked",), False),
        ("final-gate.json", ("scientificDisposition",), "blocked"),
        ("final-gate.json", ("checks", "deliveryMeasurements"), False),
        ("final-gate.json", ("checks",), {}),
        ("final-gate.json", ("evidenceBindings", "candidateBindingSha256"), "0" * 64),
        ("final-gate.json", ("evidenceBindings", "deliveryTraceSha256"), "0" * 64),
        ("final-gate.json", ("promotionEvidence", "ownerEvidenceSha256"), "0" * 64),
        ("final-gate.json", ("promotionEvidence", "integrationMergeEvidenceSha256"), "0" * 64),
        ("final-gate.json", ("promotionEvidence", "promotionSha256"), "0" * 64),
        ("owner-attestation.json", ("decision",), "rejected"),
        ("owner-attestation.json", ("candidateBindingSha256",), "0" * 64),
        ("promotion.json", ("macCandidateBindingSha256",), "0" * 64),
        ("promotion.json", ("ownerEvidenceSha256",), "0" * 64),
        ("promotion.json", ("integrationMergeEvidenceSha256",), "0" * 64),
        ("candidate-binding.json", ("releaseId",), "detached"),
        ("candidate-binding.json", ("releaseContractId",), "detached"),
        ("browser-trace-macos-arm64.json", ("candidate", "releaseId"), "detached"),
        ("browser-trace-macos-arm64.json", ("candidate", "manifestSha256"), "0" * 64),
        ("browser-trace-macos-arm64.json", ("candidate", "artifactHashes"), {}),
        ("browser-trace-macos-arm64.json", ("candidate", "artifactByteSizes"), {}),
    ],
)
def test_rejects_every_owner_gate_and_binding_mutation(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    field: tuple[str, ...],
    value: Any,
) -> None:
    original = projection_bundle_module._read_json

    def mutated_read(path: Path) -> dict[str, Any]:
        document = deepcopy(original(path))
        if path.name == name:
            target = document
            for key in field[:-1]:
                target = target[key]
            target[field[-1]] = value
        return document

    monkeypatch.setattr(projection_bundle_module, "_read_json", mutated_read)
    with pytest.raises(ScienceContractError):
        load_reviewed_cog_identities(REPOSITORY_ROOT)


def test_rejects_owner_checksum_inventory_mutation(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(REPOSITORY_ROOT / "src/pipeline", repository / "src/pipeline")
    checksums = (
        repository / "src/pipeline/evidence/ar6-regional-release/owner-promotion/checksums.txt"
    )
    checksums.write_text(checksums.read_text() + "corrupt\n")
    with pytest.raises(ScienceContractError, match="checksum inventory"):
        load_reviewed_cog_identities(repository)


def _classic_tiff(
    *, marker: bytes = b"II", magic: int = 42, offset: int = 192, count: int = 21
) -> bytes:
    data = bytearray(512)
    data[:2] = marker
    data[2:4] = magic.to_bytes(2, "little")
    data[4:8] = offset.to_bytes(4, "little")
    if offset + 2 <= len(data):
        data[offset : offset + 2] = count.to_bytes(2, "little")
    return bytes(data)


@pytest.mark.parametrize(
    "data",
    [
        b"II\x2a\x00",
        _classic_tiff(marker=b"ZZ"),
        _classic_tiff(magic=99),
        _classic_tiff(offset=8),
        _classic_tiff(offset=511),
        _classic_tiff(count=65535),
        _classic_tiff(count=0),
        b"II\x2b\x00\x08\x00\x01\x00" + (b"\x00" * 504),
        b"II\x2b\x00\x04\x00\x00\x00" + (b"\x00" * 504),
    ],
)
def test_tiff_reader_rejects_malformed_headers_and_directories(
    tmp_path: Path,
    data: bytes,
) -> None:
    root = tmp_path / "fixture"
    path = root / "test.tif"
    path.parent.mkdir()
    path.write_bytes(data)
    identity = CogArtifactIdentity("test.tif", len(data), "0" * 64)
    access = cog_range_module._ValidatedRangeAccess(identity, data, LocalRangeTransport(root))
    with pytest.raises(ScienceContractError):
        cog_range_module._validate_tiff_reader_path(access)
