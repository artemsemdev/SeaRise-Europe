"""Closed decoded parity oracle for visual boundary PMTiles."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping

import searise_pipeline.release.boundary_pmtiles as boundary_pmtiles
from searise_pipeline.science import ScienceContractError

from .test_boundary_pmtiles_structure import GEOJSON, _source


def _loaded_source(tmp_path: Path) -> object:
    return boundary_pmtiles._load_source(
        _source(tmp_path), GEOJSON["support-boundary"], role="support-boundary"
    )


def _decoded(
    source: object,
    *,
    geometry: object | None = None,
    extent: int | None = None,
) -> dict[str, object]:
    feature = {
        "id": source.specification.feature_id,
        "properties": boundary_pmtiles._writer_feature_properties(source),
        "geometry": geometry or mapping(source.geometry),
    }
    layer = {
        "properties": {
            "extent": extent or boundary_pmtiles._MVT_EXTENT,
            "layer": source.specification.layer_id,
            "version": 2,
        },
        "features": [feature],
    }
    return {"features": [{"features": [layer]}]}


def test_angular_error_model_is_derived_from_z6_mvt_quantization(tmp_path: Path) -> None:
    source = _loaded_source(tmp_path)
    assert boundary_pmtiles._generation_parameters(source)["angular_error_model"] == {
        "comparison": (
            "symmetric-vertex-to-boundary-discrete-distance-plus-per-axis-envelope"
        ),
        "coordinate_error_degrees": 360 / 2**23,
        "geometry_tolerance_degrees": 2**0.5 * 360 / 2**23,
        "maximum_rounding_stages": 2,
        "model": "web-mercator-mvt-quantization-plus-tile-clipping",
        "per_stage_coordinate_error_degrees": 180 / 2**23,
        "quantization_step_degrees": 360 / 2**23,
    }


def test_decoded_boundary_geometry_and_properties_are_independently_checked(
    tmp_path: Path,
) -> None:
    source = _loaded_source(tmp_path)
    fragments, parity = boundary_pmtiles._validate_decoded_document(
        _decoded(source), source
    )
    assert fragments == 1
    assert parity["distance"]["symmetricMaximumDegrees"] == 0
    unsafe = _decoded(source)
    unsafe["features"][0]["features"][0]["features"][0]["properties"]["analytical_lookup"] = (
        "allowed"
    )
    with pytest.raises(ScienceContractError, match="properties"):
        boundary_pmtiles._validate_decoded_document(unsafe, source)


def test_geometry_tolerance_accepts_exact_axial_and_diagonal_thresholds(
    tmp_path: Path,
) -> None:
    source = _loaded_source(tmp_path)
    source = replace(source, geometry=box(0, 0, 1, 1))
    coordinate_tolerance = boundary_pmtiles._COORDINATE_ERROR_DEGREES

    axial_at_threshold = affinity.translate(
        source.geometry, xoff=coordinate_tolerance
    )
    assert (
        boundary_pmtiles._validate_decoded_document(
            _decoded(source, geometry=mapping(axial_at_threshold)), source
        )[0]
        == 1
    )
    axial_over_threshold = affinity.translate(
        source.geometry, xoff=coordinate_tolerance + 1e-8
    )
    with pytest.raises(ScienceContractError, match="geometry parity"):
        boundary_pmtiles._validate_decoded_document(
            _decoded(source, geometry=mapping(axial_over_threshold)), source
        )

    diagonal_at_threshold = affinity.translate(
        source.geometry,
        xoff=coordinate_tolerance,
        yoff=coordinate_tolerance,
    )
    assert (
        boundary_pmtiles._validate_decoded_document(
            _decoded(source, geometry=mapping(diagonal_at_threshold)), source
        )[0]
        == 1
    )
    diagonal_over_threshold = affinity.translate(
        source.geometry,
        xoff=coordinate_tolerance + 1e-8,
        yoff=coordinate_tolerance + 1e-8,
    )
    with pytest.raises(ScienceContractError, match="geometry parity"):
        boundary_pmtiles._validate_decoded_document(
            _decoded(source, geometry=mapping(diagonal_over_threshold)), source
        )


def test_geometry_tolerance_rejects_topology_loss(tmp_path: Path) -> None:
    source = _loaded_source(tmp_path)
    tolerance = boundary_pmtiles._GEOMETRY_TOLERANCE_DEGREES
    outer = box(0, 0, 1, 1)
    hole = box(
        0.5 - tolerance / 4,
        0.5 - tolerance / 4,
        0.5 + tolerance / 4,
        0.5 + tolerance / 4,
    )
    polygon_with_hole = Polygon(outer.exterior.coords, [hole.exterior.coords])
    island = box(
        0.5 - tolerance / 16,
        0.5 - tolerance / 16,
        0.5 + tolerance / 16,
        0.5 + tolerance / 16,
    )
    nearby_fragment = box(
        1 + tolerance / 4,
        0,
        1 + tolerance / 2,
        tolerance / 4,
    )
    topology_losses = [
        (polygon_with_hole, outer),
        (MultiPolygon([polygon_with_hole, island]), polygon_with_hole),
        (MultiPolygon([outer, nearby_fragment]), outer),
    ]

    for expected, decoded in topology_losses:
        topology_source = replace(source, geometry=expected)
        with pytest.raises(ScienceContractError, match="geometry parity"):
            boundary_pmtiles._validate_decoded_document(
                _decoded(topology_source, geometry=mapping(decoded)), topology_source
            )


def test_geometry_tolerance_rejects_compensating_hole_mutation(tmp_path: Path) -> None:
    source = _loaded_source(tmp_path)
    outer = box(0, 0, 10, 10)
    source_hole = box(2, 2, 3, 3)
    replacement_hole = box(7, 7, 8, 8)
    expected = Polygon(outer.exterior.coords, [source_hole.exterior.coords])
    decoded = Polygon(outer.exterior.coords, [replacement_hole.exterior.coords])
    assert boundary_pmtiles._polygon_topology(expected) == (
        boundary_pmtiles._polygon_topology(decoded)
    )
    topology_source = replace(source, geometry=expected)
    with pytest.raises(ScienceContractError, match="geometry parity"):
        boundary_pmtiles._validate_decoded_document(
            _decoded(topology_source, geometry=mapping(decoded)), topology_source
        )


def test_indexed_directed_distance_matches_independent_fixture_oracle() -> None:
    source = Polygon(
        box(0, 0, 4, 4).exterior.coords,
        [box(1, 1, 2, 2).exterior.coords],
    )
    decoded = affinity.translate(source, xoff=0.125, yoff=-0.0625)
    indexed, count = boundary_pmtiles._indexed_directed_vertex_boundary_distance(
        source, decoded
    )
    coordinates = [
        coordinate
        for ring in boundary_pmtiles._polygon_rings(source)
        for coordinate in ring.coords
    ]
    reference = max(Point(coordinate).distance(decoded.boundary) for coordinate in coordinates)
    assert count == len(coordinates)
    assert indexed == pytest.approx(reference, rel=0, abs=1e-15)


def test_visual_segmentization_preserves_canonical_source(tmp_path: Path) -> None:
    source = _loaded_source(tmp_path)
    canonical_wkb = source.geometry.wkb
    visual, evidence = boundary_pmtiles._visual_geometry(source.geometry)
    assert source.geometry.wkb == canonical_wkb
    assert visual.is_valid
    assert boundary_pmtiles._polygon_topology(visual) == (
        boundary_pmtiles._polygon_topology(source.geometry)
    )
    assert evidence["canonicalSourceModified"] is False
    assert evidence["maximumSegmentLengthDegrees"] == 0.10
    assert evidence["distance"]["symmetricMaximumDegrees"] <= 1e-12


def test_profile_matrix_compares_detail_14_and_17_with_and_without_segmentization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _loaded_source(tmp_path)
    outer = box(0, 0, 1, 1)
    hole = box(0.49, 0.49, 0.51, 0.51)
    source = replace(
        source,
        geometry=Polygon(outer.exterior.coords, [hole.exterior.coords]),
    )
    monkeypatch.setattr(boundary_pmtiles, "_load_source", lambda *_a, **_k: source)
    monkeypatch.setattr(
        boundary_pmtiles.BoundaryVectorToolPaths,
        "validate",
        lambda *_a, **_k: None,
    )

    def pinned_tool(command: list[str]) -> str:
        output = next(
            (value.removeprefix("--output=") for value in command if value.startswith("--output=")),
            None,
        )
        if output is not None:
            Path(output).write_bytes("\n".join(command).encode())
            return ""
        if "verify" in command:
            return ""
        archive = Path(command[-1])
        detail = 14 if "detail-14" in archive.name else 17
        geometry = outer if detail == 14 else source.geometry
        return json.dumps(
            _decoded(source, geometry=mapping(geometry), extent=2**detail)
        )

    monkeypatch.setattr(boundary_pmtiles, "_run", pinned_tool)
    tools = boundary_pmtiles.BoundaryVectorToolPaths(
        tippecanoe=tmp_path / "tippecanoe",
        decode=tmp_path / "tippecanoe-decode",
        pmtiles=tmp_path / "pmtiles",
        tippecanoe_source=tmp_path / "source",
        tippecanoe_build_receipt=tmp_path / "receipt",
        pmtiles_distribution_asset=tmp_path / "asset",
        platform="darwin-arm64",
    )
    profiles = boundary_pmtiles.evaluate_boundary_profile_matrix(
        tmp_path / "source.parquet",
        tmp_path / "source.geojson",
        role="support-boundary",
        contract={},
        tools=tools,
    )
    assert [(profile["fullDetail"], profile["passed"]) for profile in profiles] == [
        (14, False),
        (14, False),
        (17, True),
        (17, True),
    ]
    assert [profile["visualIntermediary"]["method"] for profile in profiles] == [
        "none",
        "shapely-segmentize",
        "none",
        "shapely-segmentize",
    ]


def test_decoded_oracle_rejects_common_mode_writer_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _loaded_source(tmp_path)
    original = boundary_pmtiles._writer_feature_properties

    def unsafe_properties(value: object) -> dict[str, object]:
        properties = original(value)
        properties["publication_eligible"] = True
        properties["unsafe_claim"] = "canonical"
        return properties

    monkeypatch.setattr(boundary_pmtiles, "_writer_feature_properties", unsafe_properties)
    with pytest.raises(ScienceContractError, match="properties"):
        boundary_pmtiles._validate_decoded_document(_decoded(source), source)
