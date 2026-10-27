"""Batch experiment contracts: actual calculations, source separation, reproducible artifacts."""

from copy import deepcopy
import csv
from decimal import Decimal
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app import replan_experiments as experiments


FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = FIXTURES / "replan_experiments_simulation.json"


def temporary_manifest(tmp_path, cases):
    (tmp_path / "input.json").write_bytes((FIXTURES / "wf_replan_simulation.json").read_bytes())
    manifest = {"format_version": 1, "experiment_id": "simulation-test", "description": "人工模拟，未调用AgentArts",
                "cases": cases}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def case(case_id="normal", **changes):
    return {"case_id": case_id, "category": "normal", "data_type": "simulation",
            "origin": "hand_authored_fixture", "input_file": "input.json", "patches": [], **changes}


def test_minimal_dataset_records_real_outcomes_without_changing_existing_guards():
    report = experiments.run_experiment(MANIFEST)
    cases = {item["case_id"]: item for item in report["cases"]}
    expected = {
        "normal": "successfully_adapted", "continuous_old": "rejected",
        "continuous_repaired": "successfully_adapted", "no_safe_candidate": "needs_information",
        "locked_conflict": "rejected", "budget_insufficient": "rejected",
        "evidence_missing": "needs_information", "old_version": "rejected",
        "missing_date": "needs_information", "return_semantics": "needs_information",
        "candidate_id_conflict": "rejected",
    }
    assert {key: item["adapter_result"]["status"] for key, item in cases.items()} == expected
    summary = report["summary"]
    assert summary["executed_case_count"] == 11
    assert summary["case_adapter_status_counts"] == {"successfully_adapted": 2, "needs_information": 4, "rejected": 5}
    assert summary["candidate_validation_counts"] == {"PASS": 3, "FAIL": 3, "UNKNOWN": 3}
    assert summary["candidate_count"] == 9
    assert summary["cases_without_candidates"] == 2
    assert summary["metrics"]["changed_activity_count"] == {"sum": 8, "available_count": 7, "unavailable_count": 2}
    assert summary["metrics"]["added_activity_count"]["sum"] == 1
    assert summary["metrics"]["budget_delta_cny"]["sum"] == "200.00"
    assert summary["metrics"]["locked_activity_violations"]["total"] == 1
    assert summary["metrics"]["unchanged_activity_retention_rate"]["mean"] == "0.4285714285714285714285714286"
    assert summary["adapter_failure_reasons"]["revision_conflict"] == 1
    assert summary["adapter_failure_reasons"]["return_deadline_semantics_unresolved"] == 1
    assert summary["adapter_failure_reasons"]["invalid_action"] == 1
    for item in cases.values():
        assert item["execution_status"] == "executed"
        assert item["data_type"] == "simulation"
        assert item["input_sha256"]
        assert item["source_file_sha256"]
        assert item["resolved_input"]["data_type"] == "simulation"
        assert "--case" in item["reproduce_command"]
        assert item["case_id"] in item["reproduce_command"]
    assert cases["return_semantics"]["adapter_result"]["options"][0]["draft_request"] is None
    assert cases["candidate_id_conflict"]["adapter_result"]["options"][0]["draft_request"] is None


def test_unavailable_metrics_and_absent_candidates_are_not_zero_or_fabricated_unknowns():
    report = experiments.run_experiment(MANIFEST, case_ids=["missing_date", "old_version"])
    summary = report["summary"]
    assert summary["candidate_validation_counts"] == {"PASS": 0, "FAIL": 0, "UNKNOWN": 1}
    assert summary["metrics"]["budget_delta_cny"] == {"sum": None, "available_count": 0, "unavailable_count": 1}
    assert summary["metrics"]["unchanged_activity_retention_rate"]["mean"] is None
    assert summary["metrics"]["adapter_elapsed_ms"]["sum"] is None


def test_runner_calls_existing_adapter_once_per_executed_case(monkeypatch):
    actual = experiments.adapt_replan
    calls = []

    def tracked(bundle, *, measure=False):
        calls.append(deepcopy(bundle))
        return actual(bundle, measure=measure)

    monkeypatch.setattr(experiments, "adapt_replan", tracked)
    experiments.run_experiment(MANIFEST, case_ids=["normal", "locked_conflict"])
    assert len(calls) == 2


def test_future_real_unknown_and_conflicting_sources_never_enter_simulation_statistics(tmp_path, monkeypatch):
    path = temporary_manifest(tmp_path, [case(), case("future", data_type="agentarts_real", origin="declared_future_output"),
                                          case("unknown", data_type=None, origin="unknown"),
                                          case("mismatch", input_file="mismatch.json")])
    mismatch = json.loads((tmp_path / "input.json").read_text(encoding="utf-8"))
    mismatch["data_type"] = "agentarts_real"
    (tmp_path / "mismatch.json").write_text(json.dumps(mismatch), encoding="utf-8")
    actual = experiments.adapt_replan
    calls = []

    def tracked(bundle, *, measure=False):
        calls.append(bundle)
        return actual(bundle, measure=measure)

    monkeypatch.setattr(experiments, "adapt_replan", tracked)
    report = experiments.run_experiment(path)
    assert len(calls) == 1
    assert report["summary"]["executed_case_count"] == 1
    assert report["summary"]["excluded_case_count"] == 3
    assert report["summary"]["candidate_validation_counts"] == {"PASS": 1, "FAIL": 0, "UNKNOWN": 0}
    assert all(item["adapter_result"] is None and item["resolved_input"] is None for item in report["cases"][1:])
    assert report["source_groups"]["agentarts_real"]["executed_case_count"] == 0
    assert report["source_groups"]["unknown"]["executed_case_count"] == 0


def test_fixture_source_marker_cannot_be_rewritten_by_scenario_patches(tmp_path):
    path = temporary_manifest(tmp_path, [case(patches=[{"op": "replace", "path": "/data_type", "value": "simulation"}])])
    item = experiments.run_experiment(path)["cases"][0]
    assert item["execution_status"] == "error"
    assert item["execution_issues"][0]["code"] == "invalid_patch"
    assert item["adapter_result"] is None


def test_invalid_case_is_recorded_and_does_not_discard_following_case(tmp_path):
    path = temporary_manifest(tmp_path, [case("bad", input_file="broken.json"), case()])
    (tmp_path / "broken.json").write_text("{broken", encoding="utf-8")
    report = experiments.run_experiment(path)
    assert [item["execution_status"] for item in report["cases"]] == ["error", "executed"]
    assert report["cases"][0]["execution_issues"][0]["code"] == "invalid_json"
    assert report["summary"]["error_case_count"] == 1
    assert report["summary"]["candidate_validation_counts"]["PASS"] == 1


@pytest.mark.parametrize("malformed", ["overflow", "surrogate"])
def test_unserializable_case_input_does_not_abort_batch_or_poison_export(tmp_path, malformed):
    path = temporary_manifest(tmp_path, [case("bad", input_file="bad.json"), case()])
    bundle = json.loads((tmp_path / "input.json").read_text(encoding="utf-8"))
    if malformed == "overflow":
        bundle["workflow_output"]["options"][0]["additional_estimated_cost_cny"] = "EXPONENT_SENTINEL"
        raw = json.dumps(bundle).replace('"EXPONENT_SENTINEL"', "1e400")
    else:
        bundle["workflow_output"]["warnings"] = ["\ud800"]
        raw = json.dumps(bundle)
    (tmp_path / "bad.json").write_text(raw, encoding="utf-8")
    report = experiments.run_experiment(path)
    assert [item["execution_status"] for item in report["cases"]] == ["error", "executed"]
    assert report["cases"][0]["execution_issues"][0]["code"] == "invalid_json"
    assert report["cases"][0]["resolved_input"] is None
    paths = experiments.write_reports(report, tmp_path / "results")
    saved = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert saved["summary"]["executed_case_count"] == 1
    assert saved["summary"]["error_case_count"] == 1


def test_unexpected_adapter_exception_is_an_execution_error_not_a_fake_rejection(tmp_path, monkeypatch):
    path = temporary_manifest(tmp_path, [case()])

    def fail(*args, **kwargs):
        raise RuntimeError("simulation: deliberate failure")

    monkeypatch.setattr(experiments, "adapt_replan", fail)
    report = experiments.run_experiment(path)
    assert report["cases"][0]["execution_status"] == "error"
    assert report["cases"][0]["execution_issues"][0]["code"] == "adapter_exception"
    assert report["summary"]["candidate_validation_counts"] == {"PASS": 0, "FAIL": 0, "UNKNOWN": 0}


@pytest.mark.parametrize("input_file", ["../outside.json", "C:/outside.json", "input.sqlite3"])
def test_referenced_inputs_must_be_json_inside_fixture_directory(tmp_path, input_file):
    path = temporary_manifest(tmp_path, [case(input_file=input_file)])
    item = experiments.run_experiment(path)["cases"][0]
    assert item["execution_status"] == "error"
    assert item["execution_issues"][0]["code"] == "unsafe_fixture_path"


@pytest.mark.parametrize("patch", [
    {"op": "replace", "path": "/absent/value", "value": 1},
    {"op": "remove", "path": "/workflow_output/options/999"},
    {"op": "add", "path": "", "value": {}},
    {"op": "replace", "path": "/workflow_output/options/-1", "value": {}},
])
def test_invalid_patches_are_not_silently_applied(tmp_path, patch):
    path = temporary_manifest(tmp_path, [case(patches=[patch])])
    item = experiments.run_experiment(path)["cases"][0]
    assert item["execution_status"] == "error"
    assert item["execution_issues"][0]["code"] == "invalid_patch"


def test_manifest_duplicates_and_unknown_selection_fail_before_execution(tmp_path):
    path = temporary_manifest(tmp_path, [case(), case()])
    with pytest.raises(ValueError):
        experiments.run_experiment(path)
    with pytest.raises(ValueError):
        experiments.run_experiment(MANIFEST, case_ids=["nonexistent"])


def test_multi_option_csv_has_one_row_per_option_and_case_only_rows_for_no_candidate(tmp_path):
    base = json.loads((FIXTURES / "wf_replan_simulation.json").read_text(encoding="utf-8"))
    second = deepcopy(base["workflow_output"]["options"][0])
    second.update(option_id="OPT_B", feasibility="conditional")
    path = temporary_manifest(tmp_path, [case(category='说明, "引用"\n第二行', patches=[
        {"op": "add", "path": "/workflow_output/options/-", "value": second}])])
    report = experiments.run_experiment(path)
    rows = list(csv.DictReader(io.StringIO(experiments.render_csv(report))))
    assert len(rows) == 2
    assert {row["option_id"] for row in rows} == {"OPT_A", "OPT_B"}
    assert rows[0]["category"] == '说明, "引用"\n第二行'
    report = experiments.run_experiment(MANIFEST, case_ids=["old_version", "no_safe_candidate"])
    rows = list(csv.DictReader(io.StringIO(experiments.render_csv(report))))
    assert len(rows) == 2
    assert all(row["option_id"] == "" and row["candidate_validation_status"] == "" for row in rows)
    assert all(row["budget_delta_cny"] == "" for row in rows)


def test_outputs_and_input_hashes_are_reproducible_and_existing_outputs_are_preserved(tmp_path):
    before = MANIFEST.read_bytes(), (FIXTURES / "wf_replan_simulation.json").read_bytes()
    first = experiments.run_experiment(MANIFEST)
    second = experiments.run_experiment(MANIFEST)
    assert first == second
    a = experiments.write_reports(first, tmp_path / "first")
    b = experiments.write_reports(second, tmp_path / "second")
    assert set(a) == {"json", "csv", "markdown"}
    assert all(a[key].read_bytes() == b[key].read_bytes() for key in a)
    with pytest.raises(FileExistsError):
        experiments.write_reports(first, tmp_path / "first")
    assert a["json"].read_bytes() == b["json"].read_bytes()
    assert before == (MANIFEST.read_bytes(), (FIXTURES / "wf_replan_simulation.json").read_bytes())


def test_timing_is_opt_in_local_measurement_and_aggregated_only_when_available():
    plain = experiments.run_experiment(MANIFEST, case_ids=["normal"])
    timed = experiments.run_experiment(MANIFEST, case_ids=["normal"], measure=True)
    assert plain["summary"]["metrics"]["adapter_elapsed_ms"]["sum"] is None
    elapsed = timed["cases"][0]["adapter_result"]["options"][0]["evaluation"]["adapter_elapsed_ms"]
    assert Decimal(elapsed) >= 0
    assert timed["summary"]["metrics"]["adapter_elapsed_ms"]["sum"] == elapsed
    assert timed["measurement"] == "local_adapter_per_option_only"


def test_cli_runs_independently_and_three_export_formats_are_byte_reproducible(tmp_path):
    command = [sys.executable, "-m", "app.replan_experiments", str(MANIFEST), "--case", "normal"]
    for directory in ["first", "second"]:
        run = subprocess.run([*command, "--output-dir", str(tmp_path / directory)],
                             capture_output=True, text=True, encoding="utf-8", check=True)
        assert json.loads(run.stdout)["executed_case_count"] == 1
    for filename in ["results.json", "results.csv", "summary.md"]:
        assert (tmp_path / "first" / filename).read_bytes() == (tmp_path / "second" / filename).read_bytes()


def test_cli_preserves_partial_results_and_exits_nonzero_on_execution_errors(tmp_path):
    path = temporary_manifest(tmp_path, [case("bad", input_file="broken.json"), case()])
    (tmp_path / "broken.json").write_text("{broken", encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "app.replan_experiments", str(path),
                          "--output-dir", str(tmp_path / "results")],
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 1
    assert json.loads(run.stdout)["error_case_count"] == 1
    saved = json.loads((tmp_path / "results" / "results.json").read_text(encoding="utf-8"))
    assert saved["summary"]["executed_case_count"] == 1
    assert saved["summary"]["candidate_validation_counts"]["PASS"] == 1


def test_exports_escape_untrusted_csv_labels_without_changing_negative_money(tmp_path):
    path = temporary_manifest(tmp_path, [case(category="=1+1", patches=[
        {"op": "replace", "path": "/context/option_support/OPT_A/charges/1/amount_cny", "value": "40.00"}])])
    report = experiments.run_experiment(path)
    rows = list(csv.DictReader(io.StringIO(experiments.render_csv(report))))
    assert rows[0]["category"] == "'=1+1"
    assert rows[0]["budget_delta_cny"] == "-10.00"
    assert report["cases"][0]["category"] == "=1+1"


def test_experiments_never_access_database_or_network(monkeypatch):
    import socket
    import sqlite3

    def forbidden(*args, **kwargs):
        raise AssertionError("batch runner must remain offline and must not open SQLite")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    report = experiments.run_experiment(MANIFEST)
    assert report["summary"]["executed_case_count"] == 11
    assert report["summary"]["error_case_count"] == 0
