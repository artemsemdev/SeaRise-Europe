"""Tests for the explicit eight-neighbour connectivity candidate."""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from searise_pipeline.science import (
    assert_scope_connectivity_approved,
    build_pending_scope_connectivity_review,
    canonical_json_bytes,
    classify_adr024_outcome,
    connectivity_comparison,
    decision_binding_sha256,
    evaluate_connectivity_controls,
    load_scope_connectivity_review,
    ocean_connected_cells,
    review_evidence_sha256,
    validate_scope_connectivity_review,
    verify_evidence_bindings,
    verify_independent_review_proofs,
)
from searise_pipeline.science.contracts import ScienceContractError

CONTRACT_DIR = Path(__file__).parents[2] / "science"
REPO_ROOT = Path(__file__).parents[4]
REVIEW_PATH = CONTRACT_DIR / "scope-connectivity-review.json"
PACKAGE_ROOT = REPO_ROOT / "src" / "pipeline" / "searise_pipeline"
LEGACY_DOMAIN = "searise_pipeline.domain"
DYNAMIC_IMPORT_PRIMITIVES = frozenset({"__import__", "import_module"})


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _is_legacy_domain(value: str) -> bool:
    return value == LEGACY_DOMAIN or value.startswith(f"{LEGACY_DOMAIN}.")


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_safe_getattr(
    node: ast.Call, path: str, parent: ast.AST | None
) -> bool:
    if len(node.args) < 2 or node.keywords:
        return False
    if _constant_string(node.args[1]) is not None:
        return True
    if path in {
        "candidate_completeness/byte_gate.py",
        "supply_chain/protected_workflow_artifacts.py",
    }:
        return (
            len(node.args) == 2
            and _is_name(node.args[0], "value")
            and _is_name(node.args[1], "field")
            and isinstance(parent, ast.Call)
            and _is_name(parent.func, "int")
            and len(parent.args) == 1
            and parent.args[0] is node
            and not parent.keywords
        )
    if path in {
        "supply_chain/candidate_evidence.py",
        "supply_chain/production_evidence.py",
    }:
        return (
            len(node.args) == 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in {"left", "right"}
            and _is_name(node.args[1], "field")
            and isinstance(parent, ast.Compare)
        )
    if path == "settlements/full_source_stage.py":
        return (
            len(node.args) == 2
            and _is_name(node.args[0], "value")
            and isinstance(node.args[1], ast.Attribute)
            and _is_name(node.args[1].value, "item")
            and node.args[1].attr == "name"
            and isinstance(parent, ast.Call)
            and _is_name(parent.func, "_json_value")
            and len(parent.args) == 1
            and parent.args[0] is node
            and not parent.keywords
        )
    if path == "settlements/spatial_asset_authority.py":
        return (
            len(node.args) == 3
            and _is_name(node.args[0], "os")
            and _is_name(node.args[1], "flag")
            and isinstance(node.args[2], ast.Constant)
            and node.args[2].value == 0
            and isinstance(parent, ast.GeneratorExp)
            and parent.elt is node
        )
    return False


def _is_safe_locals_call(node: ast.Call, parent: ast.AST | None) -> bool:
    return (
        not node.args
        and not node.keywords
        and isinstance(parent, ast.Compare)
        and isinstance(parent.left, ast.Constant)
        and type(parent.left.value) is str
        and len(parent.ops) == 1
        and isinstance(parent.ops[0], ast.In)
        and len(parent.comparators) == 1
        and parent.comparators[0] is node
    )


def _is_safe_data_dict(node: ast.Attribute, path: str, parent: ast.AST | None) -> bool:
    if not isinstance(node.ctx, ast.Load) or not isinstance(node.value, ast.Name):
        return False
    if node.value.id == "item" and path in {
        "settlements/spatial_classification.py",
        "settlements/spatial_classification_stage.py",
    }:
        return isinstance(parent, ast.ListComp) and parent.elt is node
    if (
        node.value.id == "geometry"
        and path == "settlements/spatial_classification.py"
    ):
        return isinstance(parent, ast.Dict) and node in parent.values
    if node.value.id == "evidence" and path == "settlements/spatial_toolchain.py":
        return (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Attribute)
            and _is_name(parent.func.value, "json")
            and parent.func.attr == "dumps"
            and len(parent.args) == 1
            and parent.args[0] is node
        )
    return False


def _mapping_callable_aliases(tree: ast.AST) -> dict[str, ast.AST]:
    aliases: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.NamedExpr):
            target, value = node.target, node.value
        if not isinstance(target, ast.Name) or value is None:
            continue
        from_mapping = isinstance(value, ast.Subscript) or (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr in {"get", "pop", "setdefault", "__getitem__"}
        )
        if from_mapping:
            aliases[target.id] = node
    return aliases


def _enclosing_function(
    node: ast.AST, parents: dict[int, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    parent = parents.get(id(node))
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return parent
        parent = parents.get(id(parent))
    return None


def _is_trusted_qa_callback_call(
    node: ast.Call,
    assignment: ast.AST,
    path: str,
    parents: dict[int, ast.AST],
) -> bool:
    """Recognize only the immutable, matrix-validated internal QA callback dispatch."""
    if (
        path != "candidate_completeness/qa_dispatch.py"
        or not _is_name(node.func, "validator")
        or len(node.args) != 1
        or not _is_name(node.args[0], "request")
        or node.keywords
        or not isinstance(assignment, ast.Assign)
        or len(assignment.targets) != 1
        or not _is_name(assignment.targets[0], "validator")
        or not isinstance(assignment.value, ast.Call)
        or not isinstance(assignment.value.func, ast.Attribute)
        or assignment.value.func.attr != "get"
        or not isinstance(assignment.value.func.value, ast.Attribute)
        or not _is_name(assignment.value.func.value.value, "self")
        or assignment.value.func.value.attr != "_validators"
        or len(assignment.value.args) != 1
        or not _is_name(assignment.value.args[0], "validator_id")
        or assignment.value.keywords
    ):
        return False
    function = _enclosing_function(node, parents)
    return (
        function is not None
        and function is _enclosing_function(assignment, parents)
        and function.name == "dispatch"
        and [argument.arg for argument in function.args.args] == ["self", "request"]
    )


def _retained_import_violations(source: str, package: str, path: str) -> set[str]:
    tree = ast.parse(source)
    violations: set[str] = set()
    parents = {
        id(child): node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }
    mapping_callable_aliases = _mapping_callable_aliases(tree)
    for node in ast.walk(tree):
        parent = parents.get(id(node))
        if isinstance(node, ast.Import):
            violations.update(
                alias.name for alias in node.names if _is_legacy_domain(alias.name)
            )
        elif isinstance(node, ast.ImportFrom):
            relative_name = "." * node.level + (node.module or "")
            base = importlib.util.resolve_name(relative_name, package)
            candidates = {base, *(f"{base}.{alias.name}" for alias in node.names)}
            violations.update(value for value in candidates if _is_legacy_domain(value))
            violations.update(
                f"dynamic-import:{alias.name}:{node.lineno}"
                for alias in node.names
                if alias.name in DYNAMIC_IMPORT_PRIMITIVES
            )

        if (
            isinstance(node, ast.Name)
            and node.id in DYNAMIC_IMPORT_PRIMITIVES
        ):
            violations.add(f"dynamic-import:{node.id}:{node.lineno}")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in DYNAMIC_IMPORT_PRIMITIVES
        ):
            violations.add(f"dynamic-import:{node.attr}:{node.lineno}")

        constant = _constant_string(node)
        if constant is not None:
            if _is_legacy_domain(constant):
                violations.add(constant)
            if constant in DYNAMIC_IMPORT_PRIMITIVES:
                violations.add(f"dynamic-import-literal:{constant}:{node.lineno}")

        if isinstance(node, ast.Call):
            if isinstance(node.func, (ast.Call, ast.Subscript)):
                violations.add(f"dynamic-import:computed-callable:{node.lineno}")
            if isinstance(node.func, ast.Name) and node.func.id in mapping_callable_aliases:
                assignment = mapping_callable_aliases[node.func.id]
                if not _is_trusted_qa_callback_call(node, assignment, path, parents):
                    violations.add(
                        f"dynamic-import:computed-callable-alias:{node.lineno}"
                    )
            if isinstance(node.func, ast.Name):
                if node.func.id == "getattr" and not _is_safe_getattr(
                    node, path, parent
                ):
                    violations.add(f"dynamic-import:reflection:getattr:{node.lineno}")
                elif node.func.id == "locals":
                    if not _is_safe_locals_call(node, parent):
                        violations.add(f"dynamic-import:reflection:locals:{node.lineno}")
                elif node.func.id in {
                    "setattr",
                    "vars",
                    "globals",
                    "eval",
                    "exec",
                }:
                    violations.add(
                        f"dynamic-import:reflection:{node.func.id}:{node.lineno}"
                    )

        if isinstance(node, ast.Attribute) and node.attr in {
            "__dict__",
            "__getattribute__",
            "__setitem__",
        }:
            if node.attr != "__dict__" or not _is_safe_data_dict(node, path, parent):
                violations.add(f"dynamic-import:reflection:{node.attr}:{node.lineno}")

        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and _constant_string(node.slice) == "importlib"
        ):
            violations.add(f"dynamic-import:importlib-mapping-rebind:{node.lineno}")
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "importlib"
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            violations.add(f"dynamic-import:importlib-attribute-rebind:{node.lineno}")
        if (
            isinstance(node, ast.Name)
            and node.id == "importlib"
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            violations.add(f"dynamic-import:importlib-name-rebind:{node.lineno}")

        if isinstance(node, ast.Call):
            positional = [_constant_string(argument) for argument in node.args]
            keyword = {
                item.arg: _constant_string(item.value)
                for item in node.keywords
                if item.arg is not None
            }
            relative_targets = [
                value
                for value in positional
                if value is not None and value.startswith(".")
            ]
            package_values = [
                value
                for value in [*positional[1:], keyword.get("package")]
                if value is not None
                and (
                    value == "searise_pipeline"
                    or value.startswith("searise_pipeline.")
                )
            ]
            violations.update(
                resolved
                for target in relative_targets
                for package_value in package_values
                if _is_legacy_domain(
                    resolved := importlib.util.resolve_name(target, package_value)
                )
            )
    return violations


def _module_package(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT).with_suffix("")
    parts = ["searise_pipeline", *relative.parts]
    return ".".join(parts[:-1])


def test_diagonal_cells_connect_under_eight_neighbour_rule() -> None:
    eligible = np.array(
        [
            [True, False, False],
            [False, True, False],
            [False, False, True],
        ]
    )
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    connected = ocean_connected_cells(eligible, seeds)

    np.testing.assert_array_equal(connected, eligible)


def test_nodata_barrier_leaves_inland_basin_disconnected() -> None:
    eligible = np.array(
        [
            [True, True, False, False, False],
            [True, True, False, True, True],
            [False, False, False, True, True],
        ]
    )
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    report = connectivity_comparison(eligible, seeds)

    assert report == {
        "eligibleCellCount": 8,
        "connectedCellCount": 4,
        "disconnectedCellCount": 4,
        "disconnectedFraction": 0.5,
    }


def test_seed_must_be_eligible() -> None:
    eligible = np.zeros((2, 2), dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    with pytest.raises(ValueError, match="eligible"):
        ocean_connected_cells(eligible, seeds)


def test_nodata_and_quality_masks_are_not_traversed() -> None:
    eligible = np.ones((3, 3), dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True
    nodata = np.zeros_like(eligible)
    nodata[1, :] = True
    barriers = np.zeros_like(eligible)
    barriers[0, 2] = True

    connected = ocean_connected_cells(
        eligible,
        seeds,
        nodata=nodata,
        barriers=barriers,
    )

    np.testing.assert_array_equal(
        connected,
        np.array(
            [
                [True, True, False],
                [False, False, False],
                [False, False, False],
            ]
        ),
    )


def test_four_neighbour_rule_rejects_diagonal_connection() -> None:
    eligible = np.eye(3, dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    connected = ocean_connected_cells(eligible, seeds, neighbourhood=4)

    assert int(connected.sum()) == 1


def test_independent_control_corpus_passes() -> None:
    document = json.loads(
        (CONTRACT_DIR / "connectivity-controls.json").read_text(encoding="utf-8")
    )

    report = evaluate_connectivity_controls(document)

    assert report["passed"] == report["count"] == 9


def test_scope_review_preflight_is_reproducible_and_bound() -> None:
    checked_in = load_scope_connectivity_review(REVIEW_PATH)
    rebuilt = build_pending_scope_connectivity_review(REPO_ROOT)

    assert canonical_json_bytes(rebuilt) == REVIEW_PATH.read_bytes()
    assert checked_in["review"] == {
        "approvalReady": False,
        "decisionBindingSha256": None,
        "disposition": None,
        "nextDecision": (
            "Integrate approved issue 95 bounds and issue 96 basin evidence, record both "
            "independent signed reviews, and fail closed on every disputed empirical cell "
            "before issue 98 re-evaluates Phase 0."
        ),
        "reviewedCommit": None,
        "reviewers": {
            "product": {
                "decision": "pending",
                "independenceStatement": None,
                "proof": None,
                "reviewer": None,
                "role": "product reviewer",
            },
            "scientific": {
                "decision": "pending",
                "independenceStatement": None,
                "proof": None,
                "reviewer": None,
                "role": "scientific/data reviewer",
            },
        },
        "status": "pending-independent-review",
    }
    dependency_bindings = checked_in["dependencyBindings"]
    assert [item["id"] for item in dependency_bindings] == [
        "issue-95-uncertainty-budget",
        "issue-96-basin-contract",
        "issue-96-basin-evidence",
    ]
    for binding in dependency_bindings:
        path = REPO_ROOT / binding["path"]
        assert binding["verificationStatus"] == "verified"
        assert binding["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert checked_in["dependencyStatus"] == {
        "95": {
            "approvalReady": False,
            "artifactsVerified": True,
            "publicationGateStatus": "blocked",
            "reviewStatus": "pending-independent",
        },
        "96": {
            "approvalReady": False,
            "artifactsVerified": True,
            "publicationGateStatus": "blocked",
            "reviewStatus": "pending-external",
        },
    }
    verify_evidence_bindings(checked_in, REPO_ROOT)


def test_dependency_blockers_are_derived_from_exact_bound_artifacts() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["blockingDependencies"] = [95]
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="blockers differ"):
        validate_scope_connectivity_review(review)

    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["dependencyStatus"]["95"].update(
        {
            "approvalReady": True,
            "publicationGateStatus": "approved",
            "reviewStatus": "approved",
        }
    )
    review["blockingDependencies"] = [96]
    for control in review["empiricalControls"]:
        control["observation"]["blockingIssues"] = [96]
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="dependency status changed after binding"):
        verify_evidence_bindings(review, REPO_ROOT)


def test_every_existing_control_has_expected_observed_and_review_status() -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    observations = review["controlObservations"]

    assert len(observations) == 36
    assert sum(item["domain"] == "geography" for item in observations) == 27
    assert sum(item["domain"] == "connectivity" for item in observations) == 9
    for item in observations:
        assert item["provenance"]
        assert item["expected"] == item["observed"]
        assert item["automationStatus"] == "passed"
        assert item["reviewerStatus"] == "pending-independent-review"


@pytest.mark.parametrize(
    ("in_support", "in_coastal_scope", "projection_available", "expected"),
    [
        (False, False, False, "UnsupportedGeography"),
        (False, True, True, "UnsupportedGeography"),
        (True, False, False, "OutOfScope"),
        (True, False, True, "OutOfScope"),
        (True, True, False, "DataUnavailable"),
        (True, True, True, "ProjectionAvailable"),
    ],
)
def test_adr024_outcome_precedence_is_explicit(
    in_support: bool,
    in_coastal_scope: bool,
    projection_available: bool,
    expected: str,
) -> None:
    assert (
        classify_adr024_outcome(
            in_support=in_support,
            in_coastal_scope=in_coastal_scope,
            projection_available=projection_available,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("overrides", "invalid_name"),
    [
        ({"in_support": 1}, "in_support"),
        ({"in_coastal_scope": None}, "in_coastal_scope"),
        ({"in_coastal_scope": np.bool_(True)}, "in_coastal_scope"),
        ({"projection_available": "yes"}, "projection_available"),
    ],
)
def test_adr024_outcome_rejects_non_boolean_inputs(
    overrides: dict[str, object], invalid_name: str
) -> None:
    arguments: dict[str, object] = {
        "in_support": True,
        "in_coastal_scope": True,
        "projection_available": True,
        **overrides,
    }
    with pytest.raises(
        ScienceContractError,
        match=rf"built-in bool values: {invalid_name}$",
    ):
        classify_adr024_outcome(**arguments)  # type: ignore[arg-type]


def test_retained_pipeline_has_no_legacy_domain_or_dynamic_import_mechanisms() -> None:
    mutations = (
        ("import searise_pipeline.domain", "searise_pipeline.science"),
        ("from searise_pipeline import domain", "searise_pipeline.science"),
        (
            "from ..domain.result_state import determine_result_state",
            "searise_pipeline.science",
        ),
        (
            '__import__("searise_pipeline.domain.result_state")',
            "searise_pipeline.science",
        ),
        (
            'import importlib\nimportlib.import_module("searise_pipeline.domain")',
            "searise_pipeline.science",
        ),
        (
            'import importlib as loader\nloader.import_module("searise_pipeline.domain")',
            "searise_pipeline.science",
        ),
        (
            "from importlib import import_module as load\n"
            'load("searise_pipeline.domain.result_state")',
            "searise_pipeline.science",
        ),
        (
            'import builtins as b\nb.__import__("searise_pipeline.domain")',
            "searise_pipeline.science",
        ),
        (
            "from builtins import __import__ as load\n"
            'load("searise_pipeline.domain")',
            "searise_pipeline.science",
        ),
        (
            "import importlib\nload = importlib.import_module\n"
            'load("searise_pipeline.domain")',
            "searise_pipeline.science",
        ),
        (
            'load(".domain", "searise_pipeline")',
            "searise_pipeline.science",
        ),
        (
            'load(".domain", package="searise_pipeline")',
            "searise_pipeline.science",
        ),
        (
            'load("searise_pipeline." + "domain")',
            "searise_pipeline.science",
        ),
    )
    for source, package in mutations:
        assert _retained_import_violations(source, package, "science/mutation.py")

    assert _retained_import_violations(
        'import importlib\nimportlib.import_module("duckdb")',
        "searise_pipeline.settlements",
        "settlements/spatial_toolchain.py",
    )
    rejected_duckdb_mutations = (
        'import importlib\nimportlib.import_module("sqlite")',
        'import importlib as loader\nloader.import_module("duckdb")',
        'import importlib\nimportlib.import_module("duckdb", package="searise_pipeline")',
        'import importlib\nimportlib.import_module(module_name)',
    )
    for source in rejected_duckdb_mutations:
        assert _retained_import_violations(
            source,
            "searise_pipeline.settlements",
            "settlements/spatial_toolchain.py",
        )
    assert _retained_import_violations(
        'import importlib\nimportlib.import_module("duckdb")',
        "searise_pipeline.science",
        "science/mutation.py",
    )

    nonliteral_mutations = (
        "__import__(module_name)",
        "import importlib\nimportlib.import_module(module_name)",
        "import importlib\nimportlib.import_module('.domain', package_name)",
        "import importlib\nimportlib.import_module(prefix + 'domain')",
    )
    for source in nonliteral_mutations:
        assert _retained_import_violations(
            source,
            "searise_pipeline.science",
            "science/mutation.py",
        )

    computed_callable_mutations = (
        'import importlib\ngetattr(importlib, "import_" + "module")(module_name)',
        'import builtins\ngetattr(builtins, "__im" + "port__")(module_name)',
        'import importlib\nimportlib.__dict__["import_" + "module"](module_name)',
        'vars(__builtins__)["__im" + "port__"](module_name)',
        (
            'import importlib\nprimitive = "import_" + "module"\n'
            "importlib.__dict__[primitive](module_name)"
        ),
        (
            'import importlib\nprefix = "import_"\nsuffix = "module"\n'
            "getattr(importlib, prefix + suffix)(module_name)"
        ),
        (
            'import importlib\nprefix = "import_"\nsuffix = "module"\n'
            'getattr(importlib, f"{prefix}{suffix}")(module_name)'
        ),
        (
            'import importlib\nprefix = "import_"\nsuffix = "module"\n'
            "importlib.__dict__[prefix + suffix](module_name)"
        ),
    )
    for source in computed_callable_mutations:
        assert any(
            violation.startswith("dynamic-import:")
            for violation in _retained_import_violations(
                source,
                "searise_pipeline.science",
                "science/mutation.py",
            )
        )

    untrusted_importlib_mutations = (
        (
            'import importlib\nimportlib = loader\nimportlib.import_module("duckdb")'
        ),
        (
            "import importlib\n"
            "def load(importlib):\n"
            '    return importlib.import_module("duckdb")'
        ),
        (
            "import importlib\nfrom proxy import *\n"
            'importlib.import_module("duckdb")'
        ),
    )
    for source in untrusted_importlib_mutations:
        assert _retained_import_violations(
            source,
            "searise_pipeline.settlements",
            "settlements/spatial_toolchain.py",
        )

    structural_policy_mutations = (
        (
            'import importlib\nprefix = "import_"\nsuffix = "module"\n'
            "(loader := getattr(importlib, prefix + suffix))(module_name)",
            "dynamic-import:reflection:getattr:4",
        ),
        (
            'import importlib\nprefix = "import_"\nsuffix = "module"\n'
            "if False:\n"
            "    getattr(importlib, prefix + suffix)(module_name)",
            "dynamic-import:computed-callable:5",
        ),
        (
            'import importlib\nglobals()["importlib"] = loader\n'
            'importlib.import_module("duckdb")',
            "dynamic-import:importlib-mapping-rebind:2",
        ),
        (
            'import importlib\nglobals().__setitem__("importlib", loader)\n'
            'importlib.import_module("duckdb")',
            "dynamic-import:reflection:__setitem__:2",
        ),
    )
    for source, expected in structural_policy_mutations:
        assert expected in _retained_import_violations(
            source,
            "searise_pipeline.settlements",
            "settlements/spatial_toolchain.py",
        )

    executable_shape_mutations = (
        (
            "registry[key](request)",
            "candidate_completeness/qa_dispatch.py",
            "dynamic-import:computed-callable:1",
        ),
        (
            "actions[name]()",
            "settlements/full_source_stage.py",
            "dynamic-import:computed-callable:1",
        ),
        (
            "loader = registry[key]\nloader(request)",
            "science/mutation.py",
            "dynamic-import:computed-callable-alias:2",
        ),
        (
            "loader = registry.get(key)\nloader(request)",
            "science/mutation.py",
            "dynamic-import:computed-callable-alias:2",
        ),
        (
            "getattr(acquirer, operation)(source, asset)",
            "sources/cli.py",
            "dynamic-import:computed-callable:1",
        ),
        (
            "loader = getattr(value, field)\nloader(request)",
            "candidate_completeness/byte_gate.py",
            "dynamic-import:reflection:getattr:1",
        ),
        (
            "payload = geometry.__dict__\nloader = payload[field]\nloader(request)",
            "settlements/spatial_classification.py",
            "dynamic-import:reflection:__dict__:1",
        ),
        (
            "holder.importlib = proxy",
            "science/mutation.py",
            "dynamic-import:importlib-attribute-rebind:1",
        ),
        (
            "del holder.importlib",
            "science/mutation.py",
            "dynamic-import:importlib-attribute-rebind:1",
        ),
    )
    for source, path, expected in executable_shape_mutations:
        assert expected in _retained_import_violations(
            source,
            "searise_pipeline.science",
            path,
        )

    violations = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT)
        if relative.parts[0] == "domain":
            continue
        references = _retained_import_violations(
            path.read_text(encoding="utf-8"),
            _module_package(path),
            relative.as_posix(),
        )
        if references:
            violations.append(relative.as_posix())

    assert violations == []


def test_public_states_and_sla_limit_are_distinct_and_fail_closed() -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    controls = {item["id"]: item for item in review["semanticControls"]}
    sla_controls = {item["id"]: item for item in review["slaSourceControls"]}

    assert controls["outside-coastal-scope"]["observedState"] == "OutOfScope"
    assert controls["outside-europe-support"]["observedState"] == "UnsupportedGeography"
    assert controls["support-boundary-covers"]["observedState"] == "OutOfScope"
    assert sla_controls["sla-north-boundary-below"] == {
        "expectedReasonCode": 4,
        "expectedReasonLabel": "source-nodata",
        "expectedSourceSupported": True,
        "expectedState": "DataUnavailable",
        "id": "sla-north-boundary-below",
        "latitude": 65.96875,
        "longitude": 14.03125,
        "northernLimitLatitude": 66.03125,
        "observedReasonCode": 4,
        "observedReasonLabel": "source-nodata",
        "observedSourceSupported": True,
        "observedState": "DataUnavailable",
        "provenance": (
            "One native 0.0625-degree row below the locked SLA northern limit; a "
            "deliberately missing value must use source-nodata, not coverage loss."
        ),
        "reviewerStatus": "pending-independent-review",
        "sourceId": "copernicus-marine-eur-sla-monthly",
        "sourceValueAvailable": False,
    }
    assert sla_controls["sla-north-boundary-above"]["latitude"] == 66.09375
    assert sla_controls["sla-north-boundary-above"]["observedSourceSupported"] is False
    assert sla_controls["sla-north-boundary-above"]["observedReasonCode"] == 3
    assert (
        sla_controls["sla-north-boundary-above"]["observedReasonLabel"]
        == "transform-out-of-coverage"
    )
    assert sla_controls["sla-north-boundary-above"]["observedState"] == "DataUnavailable"


def test_sla_northern_boundary_reason_cannot_be_relabelled() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    below = review["slaSourceControls"][0]
    below["observedReasonCode"] = 3
    below["observedReasonLabel"] = "transform-out-of-coverage"
    below["observedSourceSupported"] = False
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="SLA boundary observation failed"):
        validate_scope_connectivity_review(review)


def test_empirical_review_plan_covers_required_regional_failure_modes() -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    controls = review["empiricalControls"]

    assert {item["kind"] for item in controls} == {
        "port",
        "estuary",
        "lagoon",
        "island",
        "disconnected-low-terrain",
        "steep-coast",
        "diagonal-leak",
        "wbm-barrier",
        "mosaic-tile-seam",
    }
    for item in controls:
        assert item["observation"]["status"] == "blocked-by-dependencies"
        assert item["observation"]["blockingIssues"] == [95, 96]
        assert set(item["observation"]["metrics"].values()) == {None}
        assert item["reviewerStatus"] == "pending-independent-review"
    assert review["candidate"]["support"]["canonical"] is False
    assert review["candidate"]["coastalScope"] == {
        "canonical": False,
        "distanceMetres": 25000,
        "hazardExtentClaim": False,
        "role": "product-eligibility-only",
        "version": "natural-earth-5.1.1-25km-scope-v2",
    }


def test_blocked_empirical_control_cannot_contain_metrics() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["empiricalControls"][0]["observation"]["metrics"][
        "preFilterPositiveCellCount"
    ] = 1
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="invented metrics"):
        validate_scope_connectivity_review(review)

    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["empiricalControls"][-1]["observation"]["blockingIssues"] = [95]
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="blockers differ"):
        validate_scope_connectivity_review(review)


def _complete_first_empirical_control(review: dict) -> None:  # type: ignore[type-arg]
    review["empiricalControls"][0]["observation"] = {
        "status": "complete",
        "metrics": {
            "preFilterPositiveCellCount": 10,
            "postFilterPositiveCellCount": 8,
            "removedCellCount": 2,
            "removalFraction": 0.2,
            "referencePositiveCellCount": 8,
            "falsePositiveBeforeCount": 2,
            "falsePositiveAfterCount": 0,
            "falsePositiveBeforeRate": 0.2,
            "falsePositiveAfterRate": 0.0,
            "disputedCellCount": 0,
            "tileSeamMismatchCellCount": 0,
        },
        "evidence": {
            "id": "rotterdam-port-evidence",
            "path": "data/geometry/europe.geojson",
            "sha256": "0" * 64,
        },
        "blockingIssues": [],
    }
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)


def test_complete_empirical_control_requires_checksum_bound_evidence() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    _complete_first_empirical_control(review)
    review["empiricalControls"][0]["observation"]["evidence"] = None
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.13 review"):
        validate_scope_connectivity_review(review)


def test_completed_empirical_evidence_checksum_is_verified() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    _complete_first_empirical_control(review)

    with pytest.raises(ScienceContractError, match="empirical evidence changed"):
        verify_evidence_bindings(review, REPO_ROOT)


def test_observation_change_invalidates_review_evidence_hash() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["semanticControls"][0]["observedState"] = "DataUnavailable"

    with pytest.raises(ScienceContractError, match="observations checksum mismatch"):
        validate_scope_connectivity_review(review)


def test_evidence_change_invalidates_review_binding(tmp_path: Path) -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    bound = review["evidenceBindings"][0]
    target = tmp_path / bound["path"]
    target.parent.mkdir(parents=True)
    target.write_text("changed", encoding="utf-8")

    with pytest.raises(ScienceContractError, match="evidence changed after binding"):
        verify_evidence_bindings(review, tmp_path)


def _signed_blocked_review(tmp_path: Path) -> dict:  # type: ignore[type-arg]
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    reviewed_commit = "a" * 40
    review["review"].update(
        {
            "status": "decided",
            "disposition": "blocked",
            "reviewedCommit": reviewed_commit,
            "decisionBindingSha256": decision_binding_sha256(
                "blocked",
                review["evidenceBundleSha256"],
                review["reviewEvidenceSha256"],
                reviewed_commit,
            ),
        }
    )
    for key, record in review["review"]["reviewers"].items():
        private_key = Ed25519PrivateKey.generate()
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        key_path = tmp_path / f"reviewer-{key}.pem"
        key_path.write_bytes(public_bytes)
        record.update(
            {
                "decision": "blocked",
                "reviewer": f"Independent {key} reviewer",
                "independenceStatement": "I did not implement the reviewed controls.",
            }
        )
        payload = canonical_json_bytes(
            {
                "decision": record["decision"],
                "evidenceBundleSha256": review["evidenceBundleSha256"],
                "reviewEvidenceSha256": review["reviewEvidenceSha256"],
                "independenceStatement": record["independenceStatement"],
                "reviewedCommit": reviewed_commit,
                "reviewer": record["reviewer"],
                "role": record["role"],
            }
        )
        record["proof"] = {
            "kind": "ed25519-detached-signature",
            "publicKeyPath": key_path.name,
            "publicKeySha256": hashlib.sha256(public_bytes).hexdigest(),
            "signatureBase64": base64.b64encode(private_key.sign(payload)).decode("ascii"),
        }
    return review


def test_independent_reviewer_proofs_are_cryptographically_verified(
    tmp_path: Path,
) -> None:
    review = _signed_blocked_review(tmp_path)

    validate_scope_connectivity_review(review)
    verify_independent_review_proofs(review, tmp_path)

    review["review"]["reviewers"]["product"]["proof"]["signatureBase64"] = (
        base64.b64encode(b"x" * 64).decode("ascii")
    )
    with pytest.raises(ScienceContractError, match="signature is invalid"):
        verify_independent_review_proofs(review, tmp_path)


def test_decision_requires_both_named_signed_reviewers(tmp_path: Path) -> None:
    review = _signed_blocked_review(tmp_path)
    scientific = review["review"]["reviewers"]["scientific"]
    scientific.update(
        {
            "decision": "pending",
            "reviewer": None,
            "independenceStatement": None,
            "proof": None,
        }
    )

    with pytest.raises(ScienceContractError, match="both named, signed"):
        validate_scope_connectivity_review(review)


def test_review_roles_require_distinct_identities_and_keys(tmp_path: Path) -> None:
    review = _signed_blocked_review(tmp_path)
    product = review["review"]["reviewers"]["product"]
    scientific = review["review"]["reviewers"]["scientific"]
    scientific["reviewer"] = f"  {product['reviewer'].upper()}  "

    with pytest.raises(ScienceContractError, match="identities must be distinct"):
        validate_scope_connectivity_review(review)

    review = _signed_blocked_review(tmp_path)
    product = review["review"]["reviewers"]["product"]
    scientific = review["review"]["reviewers"]["scientific"]
    scientific["proof"]["publicKeyPath"] = product["proof"]["publicKeyPath"]
    scientific["proof"]["publicKeySha256"] = product["proof"]["publicKeySha256"]

    with pytest.raises(ScienceContractError, match="fingerprints must be distinct"):
        validate_scope_connectivity_review(review)


def test_automation_cannot_self_approve_the_review() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    reviewed_commit = "a" * 40
    review["review"].update(
        {
            "status": "decided",
            "disposition": "approved",
            "reviewedCommit": reviewed_commit,
            "decisionBindingSha256": decision_binding_sha256(
                "approved",
                review["evidenceBundleSha256"],
                review["reviewEvidenceSha256"],
                reviewed_commit,
            ),
        }
    )

    with pytest.raises(ScienceContractError, match="approved disposition lacks"):
        validate_scope_connectivity_review(review)


def test_pending_or_blocked_review_never_passes_the_approval_guard(
    tmp_path: Path,
) -> None:
    pending = load_scope_connectivity_review(REVIEW_PATH)
    blocked = _signed_blocked_review(tmp_path)

    with pytest.raises(ScienceContractError, match="is not approved"):
        assert_scope_connectivity_approved(pending, REPO_ROOT)
    with pytest.raises(ScienceContractError, match="is not approved"):
        assert_scope_connectivity_approved(blocked, tmp_path)
