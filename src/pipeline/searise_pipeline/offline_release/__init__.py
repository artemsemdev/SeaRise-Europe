"""Deterministic offline release-builder contracts."""

from .engine import (
    BuildRunResult,
    OutputIdentity,
    StageContext,
    StageHandler,
    StageOutcome,
    run_build,
)
from .handlers import release_handlers, validate_complete_release
from .model import (
    BuildPlan,
    BuildPlanError,
    BuildProfile,
    EnvironmentIdentity,
    FailureCode,
    FileIdentity,
    StageDefinition,
    StageFailure,
    StageName,
    ToolIdentity,
    stage_graph,
)
from .profiles import (
    CompiledProfile,
    ProfileAvailability,
    ProfileDefinition,
    compile_profile,
    load_profile_definition,
)

__all__ = [
    "BuildPlan",
    "BuildPlanError",
    "BuildProfile",
    "BuildRunResult",
    "CompiledProfile",
    "EnvironmentIdentity",
    "FailureCode",
    "FileIdentity",
    "OutputIdentity",
    "ProfileAvailability",
    "ProfileDefinition",
    "StageContext",
    "StageDefinition",
    "StageFailure",
    "StageHandler",
    "StageName",
    "StageOutcome",
    "ToolIdentity",
    "compile_profile",
    "load_profile_definition",
    "stage_graph",
    "run_build",
    "release_handlers",
    "validate_complete_release",
]
