"""Pure domain rules shared by pipeline transformations and parity tests."""

from .result_state import AssessmentSample, ResultState, determine_result_state

__all__ = ["AssessmentSample", "ResultState", "determine_result_state"]
