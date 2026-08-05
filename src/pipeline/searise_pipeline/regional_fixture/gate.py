"""Explicit methodology-gate evaluation for the Phase 0 regional build."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContracts

SCENARIOS = ("ssp1-26", "ssp2-45", "ssp5-85")
HORIZONS = (2030, 2050, 2100)


class MethodologyGateBlocked(RuntimeError):
    """A downstream release action was attempted while the gate was closed."""


@dataclass(frozen=True)
class LayerDecision:
    scenario: str
    horizon: int
    status: str
    source_lineage: Mapping[str, Any]
    blocked_by: tuple[str, ...]


@dataclass(frozen=True)
class MethodologyGate:
    state: str
    decision: str
    blockers: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    layers: tuple[LayerDecision, ...]
    generated_scientific_artifacts: tuple[str, ...]
    unlocks_phase_1: bool

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "state": self.state,
            "decision": self.decision,
            "blockers": list(self.blockers),
            "missingEvidence": list(self.missing_evidence),
            "layers": [
                {
                    "scenario": layer.scenario,
                    "horizon": layer.horizon,
                    "status": layer.status,
                    "sourceLineage": dict(layer.source_lineage),
                    "blockedBy": list(layer.blocked_by),
                }
                for layer in self.layers
            ],
            "generatedScientificArtifacts": list(self.generated_scientific_artifacts),
            "unlocksPhase1": self.unlocks_phase_1,
        }


def evaluate_methodology_gate(contracts: ScienceContracts) -> MethodologyGate:
    """Return the explicit stop/go state without inferring missing approvals."""
    source = contracts.source_semantics
    geography = contracts.geography_rules
    vertical_methodology = contracts.vertical_methodology
    blockers = (
        _blocking_decisions(source)
        + _blocking_decisions(geography)
        + _blocking_decisions(vertical_methodology)
    )
    vertical = source["verticalCompatibility"]
    if vertical["status"] != "approved":
        blockers.append("vertical-compatibility")

    pending_reviews = _pending_reviews(source, geography, vertical_methodology)
    blockers.extend(pending_reviews)
    blockers = list(dict.fromkeys(blockers))
    state = "blocked" if blockers else "approved"
    layer_status = "blocked" if blockers else "ready-for-regional-build"
    mapping = source["projection"]["mapping"]
    lineage = {
        "projection": source["projection"]["sourceKey"],
        "terrain": f"{source['terrain']['sourceId']}/{source['terrain']['release']}",
        "variable": mapping["variable"],
        "quantile": mapping["statistic"]["quantile"],
        "projectionUnits": mapping["units"],
        "terrainUnits": source["terrain"]["verticalUnits"],
        "verticalMethodology": vertical_methodology["methodId"],
    }
    layers = tuple(
        LayerDecision(
            scenario=scenario,
            horizon=horizon,
            status=layer_status,
            source_lineage=lineage,
            blocked_by=tuple(blockers),
        )
        for scenario in SCENARIOS
        for horizon in HORIZONS
    )
    decision = (
        "Stop: do not classify, package, publish, or begin Europe-scale work."
        if blockers
        else "Go: inputs are eligible for the separate regional build and review."
    )
    return MethodologyGate(
        state=state,
        decision=decision,
        blockers=tuple(blockers),
        missing_evidence=tuple(str(item) for item in vertical.get("missingEvidence", [])),
        layers=layers,
        generated_scientific_artifacts=(),
        unlocks_phase_1=False,
    )


def assert_scientific_release_allowed(gate: MethodologyGate) -> None:
    """Guard every classification, package, publication, and Phase 1 entrypoint."""
    if gate.state != "approved":
        raise MethodologyGateBlocked(
            f"Methodology gate is {gate.state}: {', '.join(gate.blockers)}"
        )


def _blocking_decisions(document: Mapping[str, Any]) -> list[str]:
    gate = document["publicationGate"]
    return [] if gate["status"] == "approved" else list(gate["blockingDecisions"])


def _pending_reviews(
    source: Mapping[str, Any],
    geography: Mapping[str, Any],
    vertical_methodology: Mapping[str, Any],
) -> list[str]:
    reviews = {
        "projection-scientific-review": source["projection"]["review"]["status"],
        "support-geography-review": geography["support"]["review"]["status"],
        "coastal-geography-review": geography["coastal"]["review"]["status"],
        "connectivity-scientific-review": geography["connectivity"]["review"]["status"],
        "vertical-methodology-review": vertical_methodology["review"]["status"],
    }
    return [name for name, status in reviews.items() if status != "approved"]
