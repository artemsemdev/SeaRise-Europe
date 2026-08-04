"""Builders for result-state tests without legacy API or database types."""

from searise_pipeline.domain.result_state import AssessmentSample


def assessment_sample(**overrides: object) -> AssessmentSample:
    values: dict[str, object] = {
        "in_europe": True,
        "in_coastal_zone": True,
        "class_value": 0,
    }
    values.update(overrides)
    return AssessmentSample(**values)  # type: ignore[arg-type]
