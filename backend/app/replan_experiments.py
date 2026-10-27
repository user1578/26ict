"""Reproducible simulation-only batches. No API, database, cloud, or planner implementation."""

import argparse
from collections import Counter
from copy import deepcopy
import csv
from decimal import Decimal, localcontext
from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Annotated, Any, Literal

import pydantic
from pydantic import Field, StringConstraints, model_validator

from .replan_adapter import adapt_replan
from .travel_schemas import Contract


CaseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ADAPTER_STATES = ("successfully_adapted", "needs_information", "rejected")
VALIDATION_STATES = ("PASS", "FAIL", "UNKNOWN")
DATA_TYPES = ("simulation", "agentarts_real", "unknown")


class ExperimentCase(Contract):
    case_id: CaseId
    category: Text
    data_type: str | None = None
    origin: Text = "unknown"
    input_file: Text
    patches: list[dict[str, Any]] = Field(default_factory=list)


class ExperimentManifest(Contract):
    format_version: Literal[1]
    experiment_id: CaseId
    description: Text
    cases: list[ExperimentCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id必须唯一")
        return self


class Patch(Contract):
    op: Literal["add", "replace", "remove"]
    path: str
    value: Any = None

    @model_validator(mode="after")
    def explicit_value(self):
        if self.op != "remove" and "value" not in self.model_fields_set:
            raise ValueError("add/replace必须显式提供value，null不等于缺失")
        return self


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _nonfinite(value):
    raise ValueError(f"非标准JSON数值：{value}")


def _load(path):
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8-sig"), parse_constant=_nonfinite)
    # parse_constant alone does not catch exponent overflow (1e400 -> inf),
    # or escaped lone surrogates that cannot be exported as UTF-8.
    _json(document).encode("utf-8")
    return raw, document


def _fixture_path(root, relative):
    target = (root / relative).resolve()
    if Path(relative).is_absolute() or not target.is_relative_to(root) or target.suffix.lower() != ".json":
        raise ValueError("输入必须为场景清单目录内的相对JSON路径")
    return target


def _array_index(token, length, *, allow_end=False):
    if not re.fullmatch(r"0|[1-9][0-9]*", token):
        raise ValueError("数组下标必须为非负规范整数")
    index = int(token)
    if index > length or (index == length and not allow_end):
        raise ValueError("数组下标越界")
    return index


def _apply_patches(source, patches):
    """Explicit JSON Pointer add/replace/remove only; never rewrite a provenance marker."""
    resolved = deepcopy(source)
    for raw in patches:
        patch = Patch.model_validate(raw)
        if not patch.path.startswith("/") or re.search(r"~(?:[^01]|$)", patch.path):
            raise ValueError("不支持根替换或无效JSON Pointer")
        parts = [part.replace("~1", "/").replace("~0", "~") for part in patch.path[1:].split("/")]
        if parts[0] == "data_type":
            raise ValueError("场景差异不能重写输入来源标记")
        parent = resolved
        for token in parts[:-1]:
            if isinstance(parent, list):
                parent = parent[_array_index(token, len(parent))]
            elif isinstance(parent, dict):
                parent = parent[token]
            else:
                raise ValueError("JSON Pointer父节点不是对象或数组")
        token = parts[-1]
        value = deepcopy(patch.value)
        if isinstance(parent, dict):
            if patch.op != "add" and token not in parent:
                raise ValueError("replace/remove目标不存在")
            if patch.op == "remove":
                del parent[token]
            else:
                parent[token] = value
        elif isinstance(parent, list):
            index = len(parent) if patch.op == "add" and token == "-" else _array_index(token, len(parent), allow_end=patch.op == "add")
            if patch.op == "add":
                parent.insert(index, value)
            elif patch.op == "remove":
                parent.pop(index)
            else:
                parent[index] = value
        else:
            raise ValueError("JSON Pointer目标父节点不是对象或数组")
    return resolved


def _command(manifest, case_ids, measure):
    # PowerShell single-quoted arguments: embedded quotes are doubled, never evaluated.
    arguments = [sys.executable, "-m", "app.replan_experiments", str(manifest)]
    for case_id in case_ids:
        arguments.extend(["--case", case_id])
    if measure:
        arguments.append("--measure")
    return "& " + " ".join("'" + str(argument).replace("'", "''") + "'" for argument in arguments)


def _execute_case(case, manifest, measure):
    record = {
        "case_id": case.case_id, "category": case.category, "origin": case.origin,
        "declared_data_type": case.data_type, "input_data_type": None,
        "data_type": case.data_type if case.data_type in DATA_TYPES else "unknown",
        "input_file": case.input_file, "source_file_sha256": None, "input_sha256": None,
        "patches": case.patches, "resolved_input": None, "adapter_result": None,
        "execution_status": "error", "execution_issues": [],
        "working_directory": str(Path(__file__).resolve().parents[1]),
        "reproduce_command": _command(manifest, [case.case_id], measure),
    }

    def stop(code, message, status="error"):
        record["execution_status"] = status
        record["execution_issues"].append({"code": code, "reason": message})
        return record

    try:
        source = _fixture_path(manifest.parent, case.input_file)
    except ValueError as error:
        return stop("unsafe_fixture_path", str(error))
    try:
        raw, original = _load(source)
        record["source_file_sha256"] = sha256(raw).hexdigest()
    except (ValueError, UnicodeError) as error:
        return stop("invalid_json", str(error))
    except OSError as error:
        return stop("input_unavailable", str(error))
    marker = original.get("data_type") if isinstance(original, dict) else None
    record["input_data_type"] = marker
    if case.data_type != "simulation":
        return stop("unsupported_source", "仅执行明确标记的simulation，真实AgentArts和未知来源均不执行", "excluded")
    if marker != "simulation":
        record["data_type"] = "unknown"
        return stop("source_mismatch", "清单与原始输入来源不一致，不能重标记后运行", "excluded")
    if case.origin not in ("hand_authored_fixture", "manual_full_replan_control"):
        record["data_type"] = "unknown"
        return stop("unknown_origin", "模拟输入还须明确标记人工构造来源", "excluded")
    try:
        resolved = _apply_patches(original, case.patches)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        return stop("invalid_patch", str(error))
    try:
        canonical = _json(resolved).encode("utf-8")
    except (ValueError, UnicodeError, TypeError) as error:
        return stop("invalid_json", str(error))
    record["resolved_input"] = resolved
    record["input_sha256"] = sha256(canonical).hexdigest()
    try:
        record["adapter_result"] = adapt_replan(resolved, measure=measure)
    except Exception as error:
        # A case boundary preserves the actual failure and lets independent cases finish.
        return stop("adapter_exception", f"{type(error).__name__}: {error}")
    record["execution_status"] = "executed"
    return record


def _total_metric(evaluations, name, *, decimal=False, mean=False, money=False):
    values = [item[name] for item in evaluations if item[name] is not None]
    result = {"available_count": len(values), "unavailable_count": len(evaluations) - len(values)}
    key = "mean" if mean else "sum"
    if not values:
        return {key: None, **result}
    with localcontext() as context:
        context.prec = 28
        total = sum((Decimal(value) for value in values), Decimal(0)) if decimal else sum(values)
        if mean:
            total /= Decimal(len(values))
    result[key] = format(total, ".2f") if money else str(total) if decimal else total
    return result


def _summarize(cases):
    executed = [item for item in cases if item["execution_status"] == "executed"]
    options = [option for item in executed for option in item["adapter_result"]["options"]]
    evaluations = [option["evaluation"] for option in options]
    reasons = Counter()
    for item in executed:
        reasons.update(issue["code"] for issue in item["adapter_result"]["issues"])
        for option in item["adapter_result"]["options"]:
            reasons.update(issue["code"] for issue in option["issues"])
    violations = [item["locked_activity_violations"] for item in evaluations if item["locked_activity_violations"] is not None]
    metrics = {
        "changed_activity_count": _total_metric(evaluations, "changed_activity_count"),
        "added_activity_count": _total_metric(evaluations, "added_activity_count"),
        "unchanged_activity_retention_rate": _total_metric(evaluations, "unchanged_activity_retention_rate", decimal=True, mean=True),
        "budget_delta_cny": _total_metric(evaluations, "budget_delta_cny", decimal=True, money=True),
        "adapter_elapsed_ms": _total_metric(evaluations, "adapter_elapsed_ms", decimal=True),
        "locked_activity_violations": {"total": sum(len(ids) for ids in violations) if violations else None,
                                       "candidates_with_violations": sum(bool(ids) for ids in violations),
                                       "available_count": len(violations), "unavailable_count": len(evaluations) - len(violations)},
    }
    return {
        "case_count": len(cases), "executed_case_count": len(executed),
        "excluded_case_count": sum(item["execution_status"] == "excluded" for item in cases),
        "error_case_count": sum(item["execution_status"] == "error" for item in cases),
        "case_adapter_status_counts": {state: sum(item["adapter_result"]["status"] == state for item in executed) for state in ADAPTER_STATES},
        "candidate_count": len(options), "cases_without_candidates": sum(not item["adapter_result"]["options"] for item in executed),
        "candidate_validation_counts": {state: sum(item["candidate_validation_status"] == state for item in evaluations) for state in VALIDATION_STATES},
        "metrics": metrics, "adapter_failure_reasons": dict(sorted(reasons.items())),
        "execution_issue_counts": dict(sorted(Counter(issue["code"] for item in cases for issue in item["execution_issues"]).items())),
    }


def run_experiment(manifest, *, case_ids=None, measure=False):
    """Execute selected fixture cases once each; all metrics come from the existing adapter/evaluator."""
    manifest = Path(manifest).resolve()
    raw, document = _load(manifest)
    config = ExperimentManifest.model_validate(document)
    selected = set(case_ids) if case_ids is not None else {case.case_id for case in config.cases}
    known = {case.case_id for case in config.cases}
    if not selected or selected - known:
        raise ValueError("场景选择为空或包含未知case_id")
    cases = [_execute_case(case, manifest, measure) for case in config.cases if case.case_id in selected]
    app = Path(__file__).resolve().parent
    sources = ("replan_experiments.py", "replan_adapter.py", "replan_evaluation.py", "replan_schemas.py",
               "travel_schemas.py", "travel_validation.py", "schemas.py", "logic.py")
    return {
        "format_version": 1, "experiment_id": config.experiment_id, "description": config.description,
        "statistics_data_type": "simulation", "source_labels_are_not_external_verification": True,
        "manifest": str(manifest), "manifest_sha256": sha256(raw).hexdigest(),
        "runtime": {"python": platform.python_version(), "pydantic": pydantic.__version__},
        "implementation_sha256": {name: sha256((app / name).read_bytes()).hexdigest() for name in sources},
        "measurement": "local_adapter_per_option_only" if measure else "not_measured",
        "working_directory": str(app.parent),
        "reproduce_command": _command(manifest, [case["case_id"] for case in cases], measure),
        "cases": cases, "summary": _summarize(cases),
        "source_groups": {kind: _summarize([case for case in cases if case["data_type"] == kind]) for kind in DATA_TYPES},
    }


CSV_FIELDS = (
    "experiment_id", "case_id", "category", "data_type", "declared_data_type", "origin", "execution_status",
    "adapter_status", "option_id", "option_status", "candidate_validation_status", "changed_activity_count",
    "added_activity_count", "unchanged_activity_retention_rate", "budget_delta_cny", "locked_activity_violations",
    "adapter_elapsed_ms", "issues", "unavailable_reasons", "source_file_sha256", "input_sha256", "reproduce_command",
)


def render_csv(report):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for case in report["cases"]:
        result = case["adapter_result"]
        for option in (result["options"] if result and result["options"] else [None]):
            row = {key: case[key] for key in ("case_id", "category", "data_type", "declared_data_type", "origin", "execution_status",
                                             "source_file_sha256", "input_sha256", "reproduce_command")}
            row.update(experiment_id=report["experiment_id"], adapter_status=result["status"] if result else None,
                       option_id=option["option_id"] if option else None, option_status=option["status"] if option else None,
                       issues=_json(case["execution_issues"] + (result["issues"] if result else []) + (option["issues"] if option else [])))
            if option:
                evaluation = option["evaluation"]
                row.update({key: evaluation[key] for key in ("candidate_validation_status", "changed_activity_count", "added_activity_count",
                            "unchanged_activity_retention_rate", "budget_delta_cny", "adapter_elapsed_ms")})
                row["locked_activity_violations"] = _json(evaluation["locked_activity_violations"]) if evaluation["locked_activity_violations"] is not None else None
                row["unavailable_reasons"] = _json(evaluation["unavailable_reasons"])
            # These are untrusted text labels, not numeric metrics. Preserve originals in JSON.
            for key in ("category", "option_id", "origin", "declared_data_type"):
                value = row.get(key)
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                    row[key] = "'" + value
            writer.writerow(row)
    return buffer.getvalue()


def _markdown(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_markdown(report):
    summary = report["summary"]
    counts = summary["candidate_validation_counts"]
    lines = [f"# {_markdown(report['experiment_id'])}", "", "仅运行人工构造的 simulation；来源标签不证明真实旅游规则已核实，未调用 AgentArts。", "",
             f"案例：{summary['case_count']}；执行：{summary['executed_case_count']}；排除：{summary['excluded_case_count']}；执行错误：{summary['error_case_count']}。",
             f"实际候选：{summary['candidate_count']}；PASS / FAIL / UNKNOWN：{counts['PASS']} / {counts['FAIL']} / {counts['UNKNOWN']}；无候选案例：{summary['cases_without_candidates']}。", "",
             "每项统计附可计算/不可计算数量；空值不计为零，未执行或没有候选的案例不虚构候选 UNKNOWN。", "",
             "| 指标 | 实际聚合结果 |", "| --- | --- |"]
    lines.extend(f"| {name} | `{_markdown(_json(value))}` |" for name, value in summary["metrics"].items())
    lines.extend(["", "| 案例 | 来源 | 执行 | 适配 | 候选 PASS/FAIL/UNKNOWN | 原因代码 |", "| --- | --- | --- | --- | --- | --- |"])
    for case in report["cases"]:
        result = case["adapter_result"]
        options = result["options"] if result else []
        statuses = [option["evaluation"]["candidate_validation_status"] for option in options]
        counts = "/".join(str(statuses.count(state)) for state in VALIDATION_STATES)
        issues = case["execution_issues"] + (result["issues"] if result else []) + [issue for option in options for issue in option["issues"]]
        reasons = ", ".join(sorted({issue["code"] for issue in issues})) or "无"
        lines.append("| " + " | ".join(_markdown(value) for value in (case["case_id"], case["data_type"], case["execution_status"],
                                                                   result["status"] if result else "未运行", counts, reasons)) + " |")
    lines.extend(["", "默认不测时；--measure 仅测本地逐候选转换与核验，不能解释为 AgentArts 推理耗时。",
                  "返程语义和候选ID冲突保留原校验，不以实验通过率为由放宽。完整输入、来源哈希、各项核验及逐案例复现命令见 results.json。", "",
                  "在记录的 backend 工作目录复现 JSON：", "", "```powershell", report["reproduce_command"], "```", ""])
    return "\n".join(lines)


def write_reports(report, output_dir):
    """Create three UTF-8 files in a NEW directory; never overwrite existing experiment artifacts."""
    contents = {"json": ("results.json", json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"),
                "csv": ("results.csv", render_csv(report)), "markdown": ("summary.md", render_markdown(report))}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    paths = {}
    for kind, (filename, content) in contents.items():
        path = output_dir / filename
        with path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(content)
        paths[kind] = path
    return paths


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Simulation-only batch replan experiments; no database or AgentArts calls")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--case", dest="case_ids", action="append", help="select case IDs; default all, manifest order preserved")
    parser.add_argument("--measure", action="store_true", help="opt in to local adapter timing, excluded from byte reproducibility")
    parser.add_argument("--output-dir", type=Path, help="NEW directory for JSON, CSV and Markdown; omit for JSON stdout")
    args = parser.parse_args()
    try:
        report = run_experiment(args.manifest, case_ids=args.case_ids, measure=args.measure)
        if args.output_dir:
            write_reports(report, args.output_dir)
            output = {"output_dir": str(args.output_dir.resolve()), **report["summary"]}
        else:
            output = report
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 1 if report["summary"]["error_case_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
