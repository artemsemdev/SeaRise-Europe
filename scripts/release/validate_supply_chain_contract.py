"""Validate versioned supply-chain evidence without making a signing claim."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from searise_pipeline.supply_chain import (
    ProtectedWorkflowArtifactError,
    SupplyChainContractError,
    extract_protected_candidate,
    extract_protected_evidence,
    load_json,
    parse_timestamp,
    publish_npm_sbom,
    publish_nuget_sbom,
    publish_python_sbom,
    validate_candidate_artifact_authority,
    validate_candidate_evidence_pair,
    validate_cosign_tool_lock,
    validate_dependency_exception,
    validate_dependency_inventory,
    validate_evidence_files,
    validate_npm_sbom,
    validate_nuget_sbom,
    validate_python_sbom,
    verify_candidate_evidence_cryptographically,
    write_candidate_artifact_authority,
)


def _sbom(value: str) -> tuple[str, Path]:
    logical_path, separator, file_path = value.partition("=")
    if not separator or not logical_path or not file_path:
        raise argparse.ArgumentTypeError("SBOM must use LOGICAL_PATH=FILE")
    return logical_path, Path(file_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    evidence = commands.add_parser("evidence")
    evidence.add_argument("--envelope", type=Path, required=True)
    evidence.add_argument("--identity-policy", type=Path, required=True)
    evidence.add_argument("--sbom", type=_sbom, action="append", required=True)
    pair = commands.add_parser("candidate-evidence-pair")
    pair.add_argument("--candidate-root", type=Path, required=True)
    pair.add_argument("--evidence-root", type=Path, required=True)
    pair.add_argument("--repository-root", type=Path, default=Path.cwd())
    pair.add_argument("--trusted-invocation-uri", required=True)
    crypto = commands.add_parser("cryptographic-verification")
    crypto.add_argument("--candidate-root", type=Path, required=True)
    crypto.add_argument("--evidence-root", type=Path, required=True)
    crypto.add_argument("--repository-root", type=Path, default=Path.cwd())
    crypto.add_argument("--controlled-build-run-id", required=True)
    crypto.add_argument("--cosign-executable", type=Path, required=True)
    crypto.add_argument("--cosign-tool-lock", type=Path, required=True)
    crypto.add_argument("--trusted-cosign-tool-lock-sha256", required=True)
    crypto.add_argument("--receipt", type=Path, required=True)
    cosign_tool = commands.add_parser("cosign-tool-lock")
    cosign_tool.add_argument("--lock", type=Path, required=True)
    cosign_tool.add_argument("--trusted-lock-sha256", required=True)
    cosign_tool.add_argument("--executable", type=Path)
    cosign_tool.add_argument("--checksums", type=Path)
    exception = commands.add_parser("exception")
    exception.add_argument("--document", type=Path, required=True)
    exception.add_argument("--as-of", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--document", type=Path, required=True)
    inventory.add_argument("--repository-root", type=Path, default=Path.cwd())
    npm_sbom = commands.add_parser("npm-sbom")
    npm_sbom.add_argument("--lock", type=Path, required=True)
    npm_sbom.add_argument("--repository-root", type=Path, default=Path.cwd())
    npm_sbom.add_argument("--logical-path", required=True)
    npm_sbom.add_argument("--output", type=Path, required=True)
    npm_validate = commands.add_parser("npm-sbom-validate")
    npm_validate.add_argument("--sbom", type=Path, required=True)
    npm_validate.add_argument("--lock", type=Path, required=True)
    npm_validate.add_argument("--repository-root", type=Path, default=Path.cwd())
    npm_validate.add_argument("--logical-path", required=True)
    nuget_sbom = commands.add_parser("nuget-sbom")
    nuget_sbom.add_argument("--project", type=Path, required=True)
    nuget_sbom.add_argument("--lock", type=Path, required=True)
    nuget_sbom.add_argument("--repository-root", type=Path, default=Path.cwd())
    nuget_sbom.add_argument("--target-framework", required=True)
    nuget_sbom.add_argument("--output", type=Path, required=True)
    nuget_validate = commands.add_parser("nuget-sbom-validate")
    nuget_validate.add_argument("--sbom", type=Path, required=True)
    nuget_validate.add_argument("--project", type=Path, required=True)
    nuget_validate.add_argument("--lock", type=Path, required=True)
    nuget_validate.add_argument("--repository-root", type=Path, default=Path.cwd())
    nuget_validate.add_argument("--target-framework", required=True)
    python_sbom = commands.add_parser("python-sbom")
    python_sbom.add_argument("--annotation", type=Path, required=True)
    python_sbom.add_argument("--repository-root", type=Path, default=Path.cwd())
    python_sbom.add_argument("--target", required=True)
    python_sbom.add_argument("--output", type=Path, required=True)
    python_validate = commands.add_parser("python-sbom-validate")
    python_validate.add_argument("--sbom", type=Path, required=True)
    python_validate.add_argument("--annotation", type=Path, required=True)
    python_validate.add_argument("--repository-root", type=Path, default=Path.cwd())
    python_validate.add_argument("--target", required=True)
    protected_authority = commands.add_parser("protected-candidate-authority")
    protected_authority.add_argument("--run-json", type=Path, required=True)
    protected_authority.add_argument("--artifacts-json", type=Path, required=True)
    protected_authority.add_argument("--profile", required=True)
    protected_authority.add_argument("--source-revision", required=True)
    protected_authority.add_argument("--candidate-run-id", type=int, required=True)
    protected_authority.add_argument("--output", type=Path, required=True)
    protected_candidate = commands.add_parser("protected-candidate-extract")
    protected_candidate.add_argument("--archive", type=Path, required=True)
    protected_candidate.add_argument("--authority", type=Path, required=True)
    protected_candidate.add_argument("--output-root", type=Path, required=True)
    protected_evidence = commands.add_parser("protected-evidence-extract")
    protected_evidence.add_argument("--archive", type=Path, required=True)
    protected_evidence.add_argument("--expected-sha256", required=True)
    protected_evidence.add_argument("--expected-byte-size", type=int, required=True)
    protected_evidence.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "protected-candidate-authority":
            authority = validate_candidate_artifact_authority(
                args.run_json,
                args.artifacts_json,
                profile=args.profile,
                source_revision=args.source_revision,
                candidate_run_id=args.candidate_run_id,
            )
            write_candidate_artifact_authority(args.output, authority)
            print(
                f"bound protected candidate artifact {authority.artifact_id} to "
                f"run {authority.run_id}; production, publication, and scientific "
                "approval not claimed"
            )
        elif args.command == "protected-candidate-extract":
            authority = extract_protected_candidate(
                args.archive, args.output_root, args.authority
            )
            print(
                f"extracted protected candidate artifact {authority.artifact_id}; "
                "production, publication, and scientific approval not claimed"
            )
        elif args.command == "protected-evidence-extract":
            extract_protected_evidence(
                args.archive,
                args.output_root,
                expected_sha256=args.expected_sha256,
                expected_byte_size=args.expected_byte_size,
            )
            print(
                "extracted protected evidence bytes; production, publication, "
                "and scientific approval not claimed"
            )
        elif args.command == "candidate-evidence-pair":
            summary = validate_candidate_evidence_pair(
                args.candidate_root,
                args.evidence_root,
                repository_root=args.repository_root,
                trusted_invocation_uri=args.trusted_invocation_uri,
            )
            nonclaims = (
                "cryptographic verification, production, and publication not claimed"
            )
            print(
                f"validated pair: {summary.candidate_id} ({summary.sbom_count} SBOMs; {nonclaims})"
            )
        elif args.command == "cryptographic-verification":
            verify_candidate_evidence_cryptographically(
                args.candidate_root,
                args.evidence_root,
                repository_root=args.repository_root,
                controlled_build_run_id=args.controlled_build_run_id,
                cosign_executable=args.cosign_executable,
                cosign_tool_lock=args.cosign_tool_lock,
                trusted_cosign_tool_lock_sha256=args.trusted_cosign_tool_lock_sha256,
                receipt_path=args.receipt,
            )
            print(
                "verified Sigstore identity and subject digests; "
                "production, publication, and scientific approval not claimed"
            )
        elif args.command == "cosign-tool-lock":
            summary = validate_cosign_tool_lock(
                args.lock,
                trusted_lock_sha256=args.trusted_lock_sha256,
                executable_path=args.executable,
                checksum_path=args.checksums,
            )
            print(
                f"validated Cosign {summary.version} for {summary.platform}; "
                "signing and production not claimed"
            )
        elif args.command == "evidence":
            sboms = dict(args.sbom)
            if len(sboms) != len(args.sbom):
                raise SupplyChainContractError("duplicate SBOM logical path")
            envelope = validate_evidence_files(
                args.envelope,
                args.identity_policy,
                sboms,
            )
            print(f"validated synthetic evidence envelope: {envelope['candidateId']}")
        elif args.command == "exception":
            document = load_json(args.document)
            validate_dependency_exception(document, as_of=parse_timestamp(args.as_of))
            print(f"validated dependency exception: {document['exceptionId']}")
        elif args.command == "inventory":
            document = validate_dependency_inventory(
                args.document,
                repository_root=args.repository_root.resolve(),
            )
            input_count = sum(len(component["inputs"]) for component in document["components"])  # fmt: skip
            print(f"validated {input_count} dependency-defining inputs")
        elif args.command == "npm-sbom":
            document = publish_npm_sbom(
                args.output,
                args.lock,
                repository_root=args.repository_root.absolute(),
                logical_path=args.logical_path,
            )
            print(f"generated {len(document['components'])} npm components: {args.output}")  # fmt: skip
        elif args.command == "npm-sbom-validate":
            document = validate_npm_sbom(
                args.sbom,
                args.lock,
                repository_root=args.repository_root.absolute(),
                logical_path=args.logical_path,
            )
            print(f"validated {len(document['components'])} npm components: {args.sbom}")  # fmt: skip
        elif args.command == "nuget-sbom":
            document = publish_nuget_sbom(
                args.output,
                args.project,
                args.lock,
                repository_root=args.repository_root.absolute(),
                target_framework=args.target_framework,
            )
            print(
                f"generated {len(document['components'])} NuGet components "
                f"for {args.target_framework}: {args.output}"
            )
        elif args.command == "nuget-sbom-validate":
            document = validate_nuget_sbom(
                args.sbom,
                args.project,
                args.lock,
                repository_root=args.repository_root.absolute(),
                target_framework=args.target_framework,
            )
            print(
                f"validated {len(document['components'])} NuGet components "
                f"for {args.target_framework}: {args.sbom}"
            )
        elif args.command == "python-sbom":
            document = publish_python_sbom(
                args.output,
                args.annotation,
                repository_root=args.repository_root.absolute(),
                target_id=args.target,
            )
            print(
                f"generated {len(document['components'])} Python components "
                f"for {args.target}: {args.output}"
            )
        else:
            document = validate_python_sbom(
                args.sbom,
                args.annotation,
                repository_root=args.repository_root.absolute(),
                target_id=args.target,
            )
            print(
                f"validated {len(document['components'])} Python components "
                f"for {args.target}: {args.sbom}"
            )
    except (
        OSError,
        json.JSONDecodeError,
        ProtectedWorkflowArtifactError,
        SupplyChainContractError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
