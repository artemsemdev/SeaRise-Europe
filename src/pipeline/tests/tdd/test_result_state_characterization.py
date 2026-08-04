"""Target characterization for the static five-state domain mapping."""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path

import pytest

from searise_pipeline.domain.result_state import determine_result_state
from tests.builders.result_state import assessment_sample

FIXTURE_PATH = (
    Path(__file__).parents[4] / "tests/fixtures/tdd/five-state-characterization-v1.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
def test_shared_five_state_characterization(case: dict[str, object]) -> None:
    fixture_input = case["input"]
    assert isinstance(fixture_input, dict)

    sample = assessment_sample(
        in_europe=fixture_input["inEurope"],
        in_coastal_zone=fixture_input["inCoastalZone"],
        class_value=fixture_input["classValue"],
    )

    assert determine_result_state(sample) == case["expectedState"]


@pytest.mark.parametrize(
    ("in_coastal_zone", "class_value"), product((False, True, None), (0, 1, None))
)
def test_outside_europe_always_takes_precedence(
    in_coastal_zone: bool | None, class_value: int | None
) -> None:
    sample = assessment_sample(
        in_europe=False,
        in_coastal_zone=in_coastal_zone,
        class_value=class_value,
    )

    assert determine_result_state(sample) == "UnsupportedGeography"


@pytest.mark.parametrize("class_value", [0, 1, None])
def test_outside_coastal_zone_never_reports_exposure(class_value: int | None) -> None:
    sample = assessment_sample(in_coastal_zone=False, class_value=class_value)

    assert determine_result_state(sample) == "OutOfScope"
