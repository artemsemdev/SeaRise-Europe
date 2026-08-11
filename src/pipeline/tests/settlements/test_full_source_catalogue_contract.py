from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

import searise_pipeline.settlements.full_source_catalogue as full_source
from searise_pipeline.settlements.full_source_catalogue import (
    CATALOGUE_POLICY_SHA256,
    ISO_LANGUAGE_HEADER,
    NORMALIZATION_POLICY_SHA256,
    PRODUCTION_CONTRACT,
    SOURCE_LOCK_SHA256,
    FullSourceContractError,
    FullSourceStageContract,
    FullSourceStageInputs,
    LockedAsset,
    LockedMember,
    canonical_full_source_bindings_bytes,
    full_source_bindings,
    verify_full_source_inputs,
)

ROOT = Path(__file__).parents[4]
SOURCE_LOCK = ROOT / "src/pipeline/sources/source-lock.phase-1-settlements.json"
CATALOGUE_POLICY = ROOT / "src/pipeline/settlements/catalogue-policy-v1.json"
NORMALIZATION_POLICY = ROOT / "src/pipeline/settlements/normalization-policy-v2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_asset(path: Path, counts: dict[str, int]) -> LockedAsset:
    with zipfile.ZipFile(path) as archive:
        members = tuple(
            LockedMember(
                info.filename,
                hashlib.sha256(archive.read(info)).hexdigest(),
                info.file_size,
                info.compress_size,
                f"{info.CRC:08x}",
                counts[info.filename],
                ISO_LANGUAGE_HEADER if info.filename == "iso-languagecodes.txt" else None,
            )
            for info in archive.infolist()
        )
    return LockedAsset(_sha(path), path.stat().st_size, members)


def _replace_member(asset: LockedAsset, path: str, **changes: object) -> LockedAsset:
    return replace(
        asset,
        members=tuple(
            replace(member, **changes) if member.path == path else member
            for member in asset.members
        ),
    )


def _fixture(tmp_path: Path) -> tuple[FullSourceStageInputs, FullSourceStageContract]:
    places = tmp_path / "allCountries.zip"
    with zipfile.ZipFile(places, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("allCountries.txt", b"place-row-one\nplace-row-two\n")
    alternates = tmp_path / "alternateNamesV2.zip"
    with zipfile.ZipFile(alternates, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "iso-languagecodes.txt",
            ISO_LANGUAGE_HEADER + b"\r\nlanguage-row-one\nlanguage-row-two\n",
        )
        archive.writestr("alternateNamesV2.txt", b"alternate-row-one\nalternate-row-two\n")
    admin = tmp_path / "admin1CodesASCII.txt"
    admin.write_bytes(b"admin-row-one\nadmin-row-two\n")
    readme = tmp_path / "readme.txt"
    readme.write_bytes(b"GeoNames fixture license\n")
    source_lock = tmp_path / "source-lock.json"
    catalogue_policy = tmp_path / "catalogue-policy.json"
    normalization_policy = tmp_path / "normalization-policy.json"
    shutil.copyfile(SOURCE_LOCK, source_lock)
    shutil.copyfile(CATALOGUE_POLICY, catalogue_policy)
    shutil.copyfile(NORMALIZATION_POLICY, normalization_policy)
    contract = FullSourceStageContract(
        _sha(source_lock),
        _sha(catalogue_policy),
        _sha(normalization_policy),
        _archive_asset(places, {"allCountries.txt": 2}),
        _archive_asset(
            alternates,
            {"alternateNamesV2.txt": 2, "iso-languagecodes.txt": 2},
        ),
        LockedAsset(_sha(admin), admin.stat().st_size, row_count=2),
        LockedAsset(_sha(readme), readme.stat().st_size),
        minimum_free_bytes=0,
    )
    return (
        FullSourceStageInputs(
            places,
            alternates,
            admin,
            readme,
            source_lock,
            catalogue_policy,
            normalization_policy,
        ),
        contract,
    )


def test_production_contract_binds_exact_reviewed_identities_and_counts() -> None:
    assert (
        (PRODUCTION_CONTRACT.source_lock_sha256, _sha(SOURCE_LOCK)),
        (PRODUCTION_CONTRACT.catalogue_policy_sha256, _sha(CATALOGUE_POLICY)),
        (PRODUCTION_CONTRACT.normalization_policy_sha256, _sha(NORMALIZATION_POLICY)),
    ) == (
        (SOURCE_LOCK_SHA256,) * 2,
        (CATALOGUE_POLICY_SHA256,) * 2,
        (NORMALIZATION_POLICY_SHA256,) * 2,
    )
    bindings = full_source_bindings()
    assert bindings["assets"]["allCountries"]["members"][0]["rowCount"] == 13455006
    alternate_members = bindings["assets"]["alternateNames"]["members"]
    assert tuple(item["path"] for item in alternate_members) == (
        "iso-languagecodes.txt",
        "alternateNamesV2.txt",
    )
    assert {item["path"]: item["rowCount"] for item in alternate_members} == {
        "iso-languagecodes.txt": 7929,
        "alternateNamesV2.txt": 19037112,
    }
    assert bindings["assets"]["admin1"]["rowCount"] == 3865
    assert bindings["minimumFreeBytes"] == 20 * 1024**3
    assert bindings["policies"] == {
        "catalogue": {"version": "settlement-catalogue-v1", "sha256": CATALOGUE_POLICY_SHA256},
        "names": {
            "version": "settlement-normalization-v2",
            "sha256": NORMALIZATION_POLICY_SHA256,
        },
        "rawSource": {"version": "geonames-place-raw-anomalies-v1"},
    }


def test_fixture_verification_returns_stable_canonical_bindings(tmp_path: Path) -> None:
    inputs, contract = _fixture(tmp_path)
    first = verify_full_source_inputs(inputs, contract=contract)
    second = verify_full_source_inputs(inputs, contract=contract)
    assert first == second == full_source_bindings(contract)
    assert first["claimBoundary"] == {
        "decompressedMembersVerified": True,
        "stagingPerformed": False,
        "publicationClaim": False,
    }
    canonical = canonical_full_source_bindings_bytes(first)
    assert canonical == canonical_full_source_bindings_bytes(dict(reversed(first.items())))
    assert canonical.endswith(b"\n")


def test_alternate_archive_requires_official_member_order(tmp_path: Path) -> None:
    inputs, contract = _fixture(tmp_path)
    assert verify_full_source_inputs(inputs, contract=contract) == full_source_bindings(contract)

    with zipfile.ZipFile(inputs.alternate_names_zip) as archive:
        assert tuple(item.filename for item in archive.infolist()) == (
            "iso-languagecodes.txt",
            "alternateNamesV2.txt",
        )
        iso_languages = archive.read("iso-languagecodes.txt")
        alternate_names = archive.read("alternateNamesV2.txt")

    reversed_archive = tmp_path / "alternateNamesV2-reversed.zip"
    with zipfile.ZipFile(reversed_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("alternateNamesV2.txt", alternate_names)
        archive.writestr("iso-languagecodes.txt", iso_languages)
    reversed_asset = replace(
        contract.alternate_names,
        sha256=_sha(reversed_archive),
        byte_size=reversed_archive.stat().st_size,
    )
    with pytest.raises(FullSourceContractError, match="member inventory"):
        verify_full_source_inputs(
            replace(inputs, alternate_names_zip=reversed_archive),
            contract=replace(contract, alternate_names=reversed_asset),
        )
    with pytest.raises(FullSourceContractError, match="contract is malformed"):
        replace(
            contract,
            alternate_names=replace(
                contract.alternate_names,
                members=tuple(reversed(contract.alternate_names.members)),
            ),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("asset", "allCountries archive bytes differ"),
        ("member_crc", "ZIP metadata differs"),
        ("member_sha", "content or row count differs"),
        ("member_rows", "content or row count differs"),
        ("admin_rows", "admin1 input row count differs"),
        ("policy", "normalization policy bytes differ"),
        ("symlink", "regular non-symlink"),
    ],
)
def test_input_and_contract_mutations_fail_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    inputs, contract = _fixture(tmp_path)
    if mutation == "asset":
        inputs.all_countries_zip.write_bytes(b"drift")
    elif mutation.startswith("member_"):
        member = next(
            item for item in contract.alternate_names.members if item.path == "alternateNamesV2.txt"
        )
        changes = {
            "member_crc": {"crc32": "00000000"},
            "member_sha": {"sha256": "0" * 64},
            "member_rows": {"row_count": member.row_count + 1},
        }[mutation]
        contract = replace(
            contract,
            alternate_names=_replace_member(
                contract.alternate_names, "alternateNamesV2.txt", **changes
            ),
        )
    elif mutation == "admin_rows":
        contract = replace(contract, admin1=replace(contract.admin1, row_count=3))
    elif mutation == "policy":
        inputs.normalization_policy.write_text("{}", encoding="utf-8")
    else:
        link = tmp_path / "readme-link.txt"
        link.symlink_to(inputs.readme)
        inputs = replace(inputs, readme=link)
    with pytest.raises(FullSourceContractError, match=message):
        verify_full_source_inputs(inputs, contract=contract)


def test_archive_inventory_and_contract_construction_fail_closed(tmp_path: Path) -> None:
    inputs, contract = _fixture(tmp_path)
    with zipfile.ZipFile(inputs.all_countries_zip, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extra.txt", b"extra\n")
    changed_asset = replace(
        contract.all_countries,
        sha256=_sha(inputs.all_countries_zip),
        byte_size=inputs.all_countries_zip.stat().st_size,
    )
    with pytest.raises(FullSourceContractError, match="member inventory"):
        verify_full_source_inputs(inputs, contract=replace(contract, all_countries=changed_asset))
    with pytest.raises(FullSourceContractError, match="locked ZIP member identity"):
        replace(contract.all_countries.members[0], path="../unsafe")
    with pytest.raises(FullSourceContractError, match="locked ZIP member identity"):
        _replace_member(
            contract.alternate_names,
            "iso-languagecodes.txt",
            header=b"unsafe\rheader",
        )
    with pytest.raises(FullSourceContractError, match="contract is malformed"):
        replace(
            contract,
            alternate_names=_replace_member(
                contract.alternate_names,
                "iso-languagecodes.txt",
                header=b"wrong header",
            ),
        )
    with pytest.raises(FullSourceContractError, match="canonical JSON"):
        canonical_full_source_bindings_bytes({"value": float("nan")})


def test_archive_mutation_during_verification_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, contract = _fixture(tmp_path)
    zip_type = full_source.zipfile.ZipFile

    class MutatingZip(zip_type):
        def __exit__(self, *args: object) -> None:
            super().__exit__(*args)
            if Path(self.filename) == inputs.all_countries_zip:
                inputs.all_countries_zip.write_bytes(b"changed after member read")

    monkeypatch.setattr(full_source.zipfile, "ZipFile", MutatingZip)
    with pytest.raises(FullSourceContractError, match="allCountries archive bytes differ"):
        verify_full_source_inputs(inputs, contract=contract)


def test_policy_mutation_during_review_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, contract = _fixture(tmp_path)
    loader = full_source.load_normalization_policy

    def mutate_after_load(path: Path) -> object:
        result = loader(path)
        path.write_bytes(b"{}")
        return result

    monkeypatch.setattr(full_source, "load_normalization_policy", mutate_after_load)
    with pytest.raises(FullSourceContractError, match="normalization policy changed"):
        verify_full_source_inputs(inputs, contract=contract)
