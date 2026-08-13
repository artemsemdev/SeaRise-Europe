from __future__ import annotations

import hashlib
import json
from pathlib import Path

from searise_pipeline.candidate_completeness.qa_dispatch import (
    CandidateQaContext,
    QaValidationRequest,
)
from searise_pipeline.candidate_completeness.qa_matrix import ArtifactSelector
from searise_pipeline.candidate_completeness.search_shard_validator import (
    search_shard_validator,
)

ROOT = Path(__file__).resolve().parents[4]
RELEASE_ID = "searise-europe-v1.0.0-20260812-0123456789ab"


def _canonical(document: object) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def test_search_shard_uses_checksum_pinned_decoder_and_candidate_binding(
    tmp_path: Path,
) -> None:
    fixture = (
        ROOT
        / "contracts/settlements/v4/fixtures/valid/settlement-browser-search-shard.json"
    )
    document = json.loads(fixture.read_text())
    document.update(
        dataReleaseId=RELEASE_ID,
        dataProvenanceClass="real-source",
        catalogMembership="europe-core",
    )
    decoded = _canonical(document)
    tool = tmp_path / "pinned-brotli"
    tool.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        f"sys.stdout.buffer.write({decoded!r})\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)
    tool_sha256 = hashlib.sha256(tool.read_bytes()).hexdigest()
    shard = tmp_path / "search/europe-core.codepoint-trie.json.br"
    shard.parent.mkdir(parents=True)
    shard.write_bytes(b"test compressed bytes")
    request = QaValidationRequest(
        artifact_id="settlements-europe-core",
        artifact_path=shard,
        selector=ArtifactSelector(
            "settlement-search-index",
            "application/vnd.searise.search-index+json",
            "br",
        ),
        declared_sha256=hashlib.sha256(shard.read_bytes()).hexdigest(),
        candidate=CandidateQaContext(
            candidate_root=tmp_path,
            candidate_id="candidate-phase-1-real-source-20260812-0123456789ab",
            data_release_id=RELEASE_ID,
            data_provenance_class="real-source",
            manifest_sha256=None,
            artifact_count=51,
        ),
    )
    validator = search_shard_validator(
        brotli_path=tool,
        brotli_sha256=tool_sha256,
        work_directory=tmp_path / "work",
    )
    assert validator(request).status == "pass"

    wrong_tool = search_shard_validator(
        brotli_path=tool,
        brotli_sha256="0" * 64,
        work_directory=tmp_path / "work",
    )
    assert wrong_tool(request).code == "search-shard-tool"
