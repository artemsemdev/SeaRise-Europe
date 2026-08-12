"""Pure normalized settlement catalogue/domain contract."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import fields, replace
from pathlib import Path

import pytest

from searise_pipeline.settlements.alternate_names import (
    language_codes,
    parse_alternate_name_row,
    parse_iso_language_row,
)
from searise_pipeline.settlements.catalogue import (
    CATALOGUE_POLICY_SHA256,
    CATALOGUE_POLICY_VERSION,
    CATALOGUE_SNAPSHOT_DATE,
    EXPLICITLY_EXCLUDED_FEATURE_CODES,
    INCLUDED_FEATURE_CODES,
    REJECTION_PRECEDENCE,
    CatalogueNormalizationError,
    CatalogueRecordNormalization,
    load_catalogue_policy,
    normalize_catalogue,
    normalize_catalogue_record,
)
from searise_pipeline.settlements.geonames import (
    ADMIN1_SOURCE,
    ALL_COUNTRIES_SOURCE,
    parse_admin1_row,
    parse_geoname_row,
)

FIXTURES = Path(__file__).with_name("fixtures") / "geonames"
ROOT = Path(__file__).parents[4]
PLACE_MANIFEST = json.loads((FIXTURES / "fixture-manifest.json").read_text())
ALTERNATE_MANIFEST = json.loads((FIXTURES / "alternate-fixture-manifest.json").read_text())
CATALOGUE_MANIFEST = json.loads((FIXTURES / "catalogue-fixture-manifest.json").read_text())
POLICY = ROOT / "src/pipeline/settlements/catalogue-policy-v1.json"


def _rows(manifest: dict, name: str) -> list[tuple[bytes, dict]]:
    source = next(item for item in manifest["sources"] if item["fixtureFile"] == name)
    lines = (FIXTURES / name).read_bytes().splitlines()
    return [(lines[item["fixtureLine"] - 1], item) for item in source["rows"]]


def _places() -> dict[int, object]:
    return {
        metadata["sourceRecordId"]: parse_geoname_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows(PLACE_MANIFEST, "allCountries.rows.txt")
    }


def _admins() -> dict[str, object]:
    records = [
        parse_admin1_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows(PLACE_MANIFEST, "admin1CodesASCII.rows.txt")
    ]
    return {record.key: record for record in records}


def _alternates() -> list:
    return [
        parse_alternate_name_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows(ALTERNATE_MANIFEST, "alternateNamesV2.rows.txt")
    ]


def _languages() -> frozenset[str]:
    return language_codes(
        parse_iso_language_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows(ALTERNATE_MANIFEST, "iso-languagecodes.rows.txt")
    )


def _catalogue_place():
    row, metadata = _rows(CATALOGUE_MANIFEST, "catalogue-allCountries.rows.txt")[0]
    return parse_geoname_row(row, source_line=metadata["sourceLine"])


def _catalogue_admin():
    row, metadata = _rows(CATALOGUE_MANIFEST, "catalogue-admin1CodesASCII.rows.txt")[0]
    return parse_admin1_row(row, source_line=metadata["sourceLine"])


def _synthetic(record, geoname_id: int, **changes):
    lineage = replace(
        record.lineage,
        source_line=geoname_id,
        source_record_id=geoname_id,
    )
    return replace(record, geoname_id=geoname_id, lineage=lineage, **changes)


def test_catalogue_policy_and_exact_fixtures_are_immutable_and_source_bound() -> None:
    assert CATALOGUE_MANIFEST["cataloguePolicy"] == {
        "path": "src/pipeline/settlements/catalogue-policy-v1.json",
        "version": CATALOGUE_POLICY_VERSION,
        "sha256": CATALOGUE_POLICY_SHA256,
    }
    assert hashlib.sha256(POLICY.read_bytes()).hexdigest() == CATALOGUE_POLICY_SHA256
    assert load_catalogue_policy(POLICY)["nameNormalizationPolicyVersion"] == (
        "settlement-normalization-v2"
    )
    lock = ROOT / CATALOGUE_MANIFEST["sourceLock"]["path"]
    assert (
        hashlib.sha256(lock.read_bytes()).hexdigest() == CATALOGUE_MANIFEST["sourceLock"]["sha256"]
    )
    identities = {
        "catalogue-allCountries.rows.txt": (ALL_COUNTRIES_SOURCE, 19),
        "catalogue-admin1CodesASCII.rows.txt": (ADMIN1_SOURCE, 4),
    }
    for source in CATALOGUE_MANIFEST["sources"]:
        identity, width = identities[source["fixtureFile"]]
        contents = (FIXTURES / source["fixtureFile"]).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == source["fixtureSha256"]
        assert all(len(row.split(b"\t")) == width for row in contents.splitlines())
        assert (source["sourceFile"], source["sourceSha256"]) == (
            identity.source_file,
            identity.source_sha256,
        )


def test_exact_rows_build_joined_places_with_stable_ids_and_complete_lineage() -> None:
    places, admins = _places(), _admins()
    barcelona = _catalogue_place()
    catalogue = normalize_catalogue(
        [barcelona, places[3039322]],
        [*reversed(admins.values()), _catalogue_admin()],
        {3128760: list(reversed([item for item in _alternates() if item.geoname_id == 3128760]))},
        known_language_codes=_languages(),
    )
    assert (catalogue.snapshot_date, catalogue.catalogue_policy_version) == (
        CATALOGUE_SNAPSHOT_DATE,
        CATALOGUE_POLICY_VERSION,
    )
    assert (catalogue.normalization_version, catalogue.rejections) == (
        "settlement-normalization-v2",
        (),
    )
    assert [place.id for place in catalogue.places] == [
        "geonames:3039322",
        "geonames:3128760",
    ]

    ramio, barcelona = catalogue.places
    assert (ramio.source_spelling, ramio.canonical_name.value, ramio.ascii_name) == (
        "Ràmio",
        "Ràmio",
        "Ramio",
    )
    assert (ramio.admin1_code, ramio.admin1_name, ramio.population) == (
        "08",
        "Escaldes-Engordany",
        0,
    )
    assert [
        (item.source_file, item.source_line, item.source_record_id) for item in ramio.lineage
    ] == [
        ("allCountries.txt", 513, 3039322),
        ("admin1CodesASCII.txt", 7, 3338529),
    ]

    assert barcelona.id == "geonames:3128760"
    assert (barcelona.country_code, barcelona.admin1_code, barcelona.admin1_name) == (
        "ES",
        "56",
        "Catalonia",
    )
    assert [(item.value, item.language, item.script) for item in barcelona.alternate_names] == [
        ("la Ciudad Condal", "es", "Latn")
    ]
    assert [
        (item.source_file, item.source_line, item.source_record_id) for item in barcelona.lineage
    ] == [
        ("allCountries.txt", 3277115, 3128760),
        ("admin1CodesASCII.txt", 959, 3336901),
        ("alternateNamesV2.txt", 5109028, 2039069),
    ]
    assert catalogue.name_rejection_counts == (("duplicate-name", 2),)


def test_record_normalization_matches_batch_for_every_outcome() -> None:
    places, admins = _places(), _admins()
    barcelona = _catalogue_place()
    rejected = _synthetic(places[3039322], 900000010, feature_code="PPLH")
    rejected_alternate = replace(
        next(item for item in _alternates() if item.language_tag == "post"),
        geoname_id=rejected.geoname_id,
    )
    records = [rejected, barcelona, places[1482375], places[3039322]]
    admins_by_key = {**admins, "ES.56": _catalogue_admin()}
    alternates_by_id = {
        barcelona.geoname_id: [
            item for item in _alternates() if item.geoname_id == barcelona.geoname_id
        ],
        rejected.geoname_id: [rejected_alternate],
    }
    languages = _languages()

    batch = normalize_catalogue(
        records,
        admins_by_key.values(),
        alternates_by_id,
        known_language_codes=languages,
    )
    results = {
        record.geoname_id: normalize_catalogue_record(
            record,
            admins_by_key=admins_by_key,
            alternate_records=alternates_by_id.get(record.geoname_id, ()),
            known_language_codes=languages,
        )
        for record in sorted(records, key=lambda item: item.geoname_id)
    }
    ordered = tuple(results.values())
    assert all(isinstance(item, CatalogueRecordNormalization) for item in ordered)
    assert all((item.place is None) != (item.rejection is None) for item in ordered)
    assert tuple(item.place for item in ordered if item.place is not None) == batch.places
    assert tuple(item.rejection for item in ordered if item.rejection is not None) == (
        batch.rejections
    )
    assert (
        tuple(item.context_notice for item in ordered if item.context_notice is not None)
        == batch.context_notices
    )
    counts: Counter[str] = Counter()
    for item in ordered:
        assert item.name_rejection_counts == tuple(sorted(item.name_rejection_counts))
        counts.update(dict(item.name_rejection_counts))
    assert tuple(sorted(counts.items())) == batch.name_rejection_counts

    assert results[barcelona.geoname_id].name_rejection_counts == (("duplicate-name", 2),)
    assert results[places[3039322].geoname_id].place is not None
    unresolved = results[places[1482375].geoname_id]
    assert unresolved.context_notice is not None
    assert unresolved.context_notice.observed_value == "PK.03"
    excluded = results[rejected.geoname_id]
    assert excluded.rejection is not None
    assert excluded.rejection.reason == "feature-code-not-included"
    assert excluded.name_rejection_counts == ()


def test_record_normalization_rejects_invalid_lookup_inputs_exactly() -> None:
    place = _places()[3039322]
    languages = _languages()
    invalid_place = replace(
        place,
        lineage=replace(place.lineage, source_record_id=1),
    )
    with pytest.raises(CatalogueNormalizationError) as error:
        normalize_catalogue_record(
            invalid_place,
            admins_by_key={},
            alternate_records=(),
            known_language_codes=languages,
        )
    assert str(error.value) == "place lineage differs from the pinned source"

    wrong_alternate = _alternates()[0]
    with pytest.raises(CatalogueNormalizationError) as error:
        normalize_catalogue_record(
            place,
            admins_by_key={},
            alternate_records=[wrong_alternate],
            known_language_codes=languages,
        )
    assert str(error.value) == "alternate-name bucket 3039322 contains place 3039162"

    barcelona = _catalogue_place()
    alternate = next(item for item in _alternates() if item.geoname_id == barcelona.geoname_id)
    with pytest.raises(CatalogueNormalizationError) as error:
        normalize_catalogue_record(
            barcelona,
            admins_by_key={},
            alternate_records=[alternate, alternate],
            known_language_codes=languages,
        )
    assert str(error.value) == f"duplicate alternateNameId {alternate.alternate_name_id}"

    wrong_admin = _admins()["AD.05"]
    with pytest.raises(CatalogueNormalizationError) as error:
        normalize_catalogue_record(
            place,
            admins_by_key={"AD.08": wrong_admin},
            alternate_records=(),
            known_language_codes=languages,
        )
    assert str(error.value) == "admin1 lookup key AD.08 contains AD.05"


def test_record_normalization_result_rejects_impossible_states_exactly() -> None:
    places = _places()
    languages = _languages()
    accepted = normalize_catalogue_record(
        places[3039322],
        admins_by_key=_admins(),
        alternate_records=(),
        known_language_codes=languages,
    )
    rejected = normalize_catalogue_record(
        _synthetic(places[3039322], 900000011, feature_code="PPLH"),
        admins_by_key={},
        alternate_records=(),
        known_language_codes=languages,
    )
    unresolved = normalize_catalogue_record(
        places[1482375],
        admins_by_key={},
        alternate_records=(),
        known_language_codes=languages,
    )
    assert rejected.rejection is not None
    assert unresolved.context_notice is not None

    invalid_states = (
        (
            accepted,
            {"place": None},
            "record normalization must contain exactly one place or rejection",
        ),
        (
            accepted,
            {"rejection": rejected.rejection},
            "record normalization must contain exactly one place or rejection",
        ),
        (
            rejected,
            {"context_notice": unresolved.context_notice},
            "rejected record normalization cannot contain context or name rejection details",
        ),
        (
            rejected,
            {"name_rejection_counts": (("duplicate-name", 1),)},
            "rejected record normalization cannot contain context or name rejection details",
        ),
        (
            accepted,
            {"name_rejection_counts": (("z-reason", 1), ("a-reason", 1))},
            "record name rejection counts must be sorted, unique, and positive",
        ),
        (
            accepted,
            {"name_rejection_counts": (("a-reason", 1), ("a-reason", 2))},
            "record name rejection counts must be sorted, unique, and positive",
        ),
        (
            accepted,
            {"name_rejection_counts": (("a-reason", 0),)},
            "record name rejection counts must be sorted, unique, and positive",
        ),
    )
    for result, changes, message in invalid_states:
        with pytest.raises(CatalogueNormalizationError) as error:
            replace(result, **changes)
        assert str(error.value) == message


def test_inclusion_rejections_are_explicit_precedence_bound_and_order_independent() -> None:
    places = _places()
    base = places[3039322]
    candidates = [
        places[1134032],
        places[12564634],
        _synthetic(base, 900000001, feature_class="A", feature_code="ADM1", country_code=None),
        _synthetic(base, 900000002, feature_code="PPLX"),
        _synthetic(base, 900000003, country_code=None),
        _synthetic(base, 900000004, population=-1),
        _synthetic(base, 900000005, latitude=float("nan")),
        _synthetic(base, 900000006, feature_code="PPLH"),
        _synthetic(base, 900000007, feature_code="PPLQ"),
        _synthetic(base, 900000008, feature_code="PPLW"),
        _synthetic(base, 900000009, name="unsafe\x01canonical"),
    ]
    forward = normalize_catalogue(candidates, [], {}, known_language_codes=_languages())
    reverse = normalize_catalogue(reversed(candidates), [], {}, known_language_codes=_languages())
    assert forward == reverse
    assert forward.places == ()
    assert [(item.place_id, item.field, item.reason) for item in forward.rejections] == [
        ("geonames:1134032", "featureClass", "feature-class-not-populated-place"),
        ("geonames:12564634", "sourceSpelling", "unsafe-canonical-name"),
        ("geonames:900000001", "featureClass", "feature-class-not-populated-place"),
        ("geonames:900000002", "featureCode", "feature-code-not-included"),
        ("geonames:900000003", "countryCode", "country-code-missing"),
        ("geonames:900000004", "population", "negative-population"),
        ("geonames:900000005", "location", "invalid-coordinate"),
        ("geonames:900000006", "featureCode", "feature-code-not-included"),
        ("geonames:900000007", "featureCode", "feature-code-not-included"),
        ("geonames:900000008", "featureCode", "feature-code-not-included"),
        ("geonames:900000009", "sourceSpelling", "unsafe-canonical-name"),
    ]
    assert [item.lineage.source_record_id for item in forward.rejections] == [
        1134032,
        12564634,
        *range(900000001, 900000010),
    ]


def test_admin_context_is_nullable_but_duplicate_join_keys_fail_closed() -> None:
    places, admins = _places(), _admins()
    missing = replace(places[3039322], admin1_code=None)
    result = normalize_catalogue(
        [places[1482375], missing],
        admins.values(),
        {},
        known_language_codes=_languages(),
    )
    shingli, ramio = result.places
    assert (ramio.admin1_code, ramio.admin1_name) == (None, None)
    assert len(ramio.lineage) == 1
    assert (shingli.admin1_code, shingli.admin1_name) == ("03", None)
    assert len(shingli.lineage) == 1
    assert [
        (item.place_id, item.reason, item.observed_value) for item in result.context_notices
    ] == [("geonames:1482375", "admin1-code-unresolved", "PK.03")]
    assert result.context_notice_counts == (("admin1-code-unresolved", 1),)

    duplicate = replace(admins["AD.08"], name="Conflicting source row")
    with pytest.raises(CatalogueNormalizationError, match="duplicate admin1 join key AD.08"):
        normalize_catalogue(
            [places[3039322]], [admins["AD.08"], duplicate], {}, known_language_codes=_languages()
        )


def test_duplicate_place_identity_and_wrong_alternate_binding_fail_closed() -> None:
    place = _places()[3039322]
    orphan = _alternates()[0]
    with pytest.raises(CatalogueNormalizationError, match="duplicate GeoNames place id"):
        normalize_catalogue([place, place], [], {}, known_language_codes=_languages())
    with pytest.raises(CatalogueNormalizationError, match="alternate-name bucket"):
        normalize_catalogue(
            [place],
            [],
            {place.geoname_id: [_alternates()[0]]},
            known_language_codes=_languages(),
        )
    with pytest.raises(CatalogueNormalizationError, match="orphan alternate-name bucket"):
        normalize_catalogue(
            [], [], {orphan.geoname_id: [orphan]}, known_language_codes=_languages()
        )


def test_source_lineage_drift_fails_closed() -> None:
    places, admins = _places(), _admins()
    place = replace(
        places[3039322],
        lineage=replace(places[3039322].lineage, source_record_id=1),
    )
    with pytest.raises(CatalogueNormalizationError, match="place lineage"):
        normalize_catalogue([place], [], {}, known_language_codes=_languages())
    admin = replace(
        admins["AD.08"],
        lineage=replace(admins["AD.08"].lineage, source_sha256="0" * 64),
    )
    with pytest.raises(CatalogueNormalizationError, match="admin1 lineage"):
        normalize_catalogue([], [admin], {}, known_language_codes=_languages())


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("coordinateContext", "rounding", "six-decimals"),
        ("admin1Context", "unmatchedCode", "reject-place"),
        ("inclusion", "rejectionPrecedence", ["country-code-missing"]),
    ],
)
def test_catalogue_policy_is_explicit_and_fail_closed(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    policy = load_catalogue_policy(POLICY)
    assert policy["coordinateContext"] == {
        "source": "allCountries.latitude-longitude",
        "crs": "WGS84",
        "fieldOrder": ["latitude", "longitude"],
        "finiteAndInRange": True,
        "rounding": "none",
    }
    assert policy["admin1Context"]["unmatchedCode"] == "include-code-null-name"
    assert set(policy["inclusion"]["featureCodes"]) == INCLUDED_FEATURE_CODES
    assert set(policy["inclusion"]["explicitlyExcludedFeatureCodes"]) == (
        EXPLICITLY_EXCLUDED_FEATURE_CODES
    )
    assert not INCLUDED_FEATURE_CODES & EXPLICITLY_EXCLUDED_FEATURE_CODES
    assert tuple(policy["inclusion"]["rejectionPrecedence"]) == REJECTION_PRECEDENCE
    mutated = json.loads(json.dumps(policy))
    mutated[section][field] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(mutated))
    with pytest.raises(ValueError, match="bytes differ from reviewed v1"):
        load_catalogue_policy(path)


def test_domain_intentionally_has_no_spatial_or_artifact_fields() -> None:
    place = normalize_catalogue(
        [_places()[3039322]], [], {}, known_language_codes=_languages()
    ).places[0]
    names = {item.name for item in fields(place)}
    assert not names & {
        "spatial_classification",
        "distance_to_coast_meters",
        "catalog_membership",
        "geometry",
        "artifact_path",
    }
