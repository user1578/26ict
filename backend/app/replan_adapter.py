"""Side-effect-free WF_Replan simulation adapter. It never imports the store or API."""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from time import perf_counter_ns

from pydantic import ValidationError

from .replan_evaluation import evaluate_replan
from .replan_schemas import CandidateSupport, SimulationBundle, WFOption
from .travel_schemas import CreateDraft, TravelPlan


def issue(code, field, reason, option_id=None):
    return {"code": code, "field": field, "reason": reason, "option_id": option_id}


class ConversionProblem(ValueError):
    def __init__(self, code, field, reason):
        self.issue = issue(code, field, reason)


def _version(value):
    if type(value) is int and value > 0:
        return value
    match = re.fullmatch(r"v([1-9][0-9]*)", value) if isinstance(value, str) else None
    if not match:
        raise ConversionProblem("invalid_version", "base_version", "版本须为正整数或v1形式")
    return int(match[1])


def _timezone(offset):
    if offset is None:
        return None
    if not re.fullmatch(r"[+-][0-9]{2}:[0-9]{2}", offset):
        raise ConversionProblem("invalid_timezone", "context.timezone_offset", "时区须为显式UTC偏移，例如+08:00")
    hours, minutes = int(offset[1:3]), int(offset[4:6])
    if minutes >= 60 or hours * 60 + minutes > 14 * 60:
        raise ConversionProblem("invalid_timezone", "context.timezone_offset", "UTC偏移超出有效范围")
    sign = 1 if offset[0] == "+" else -1
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _timestamp(value, *, activity_id, dates, tz, field, trip):
    if value is None:
        raise ConversionProblem("missing_time", field, "时间未知，不能用正式快照时间填补模型中的null")
    try:
        if re.fullmatch(r"[0-9]{2}:[0-9]{2}(?::[0-9]{2})?", value):
            supplied_date = dates.get(activity_id)
            if supplied_date is None:
                raise ConversionProblem("missing_date", field, "只有时分，必须明确提供该活动的日期")
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", supplied_date):
                raise ValueError("invalid date")
            parsed = datetime.combine(date.fromisoformat(supplied_date), time.fromisoformat(value))
        else:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
                                r"(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?", value):
                raise ValueError("not ISO8601")
            offset = re.search(r"[+-]([0-9]{2}):([0-9]{2})$", value)
            if offset and (int(offset[2]) >= 60 or int(offset[1]) * 60 + int(offset[2]) > 14 * 60):
                raise ValueError("invalid UTC offset")
            parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            if tz is None:
                raise ConversionProblem("missing_timezone", field, "未提供时间偏移或明确的当地时区")
            parsed = parsed.replace(tzinfo=tz)
    except ValueError as error:
        if isinstance(error, ConversionProblem):
            raise
        raise ConversionProblem("invalid_time", field, "日期或ISO8601时间无效") from error
    local_date = parsed.astimezone(tz).date() if tz is not None else parsed.date()
    if ((trip.start_date is not None and local_date < trip.start_date)
            or (trip.end_date is not None and local_date > trip.end_date)):
        raise ConversionProblem("time_outside_trip", field, "活动日期超出实际提供的旅行范围")
    return parsed


def _context_issues(bundle, tz):
    context, invocation, output = bundle.context, bundle.workflow_input, bundle.workflow_output
    trip = context.trip
    problems = []
    if invocation.trip_id != trip.trip_id or output.trip_id != trip.trip_id:
        problems.append(issue("trip_mismatch", "trip_id", "工作流与正式旅行ID不一致"))
    if (_version(invocation.formal_version) != trip.current_version or _version(output.base_version) != trip.current_version
            or invocation.event_revision != trip.event_revision or invocation.history_revision != trip.history_revision
            or output.event_revision not in (None, trip.event_revision)
            or output.history_revision not in (None, trip.history_revision)):
        problems.append(issue("revision_conflict", "revision_tokens", "版本或事件/历史修订号已变化"))
    versions = context.versions
    if (len(versions) != trip.current_version or {v.version for v in versions} != set(range(1, trip.current_version + 1))
            or any(v.trip_id != trip.trip_id for v in versions)
            or trip.current_plan.trip_id != trip.trip_id or trip.current_plan.version != trip.current_version
            or next((v for v in versions if v.version == trip.current_version), None) != trip.current_plan):
        problems.append(issue("history_mismatch", "context.versions", "须提供同一旅行的全部正式版本，当前快照必须一致"))
    current = {activity.id: activity for activity in trip.current_plan.plan.activities}
    input_activities = invocation.current_plan.activities
    if (len(input_activities) != len(current) or {a.activity_id for a in input_activities} != current.keys()
            or not set(trip.locked_activity_ids) <= current.keys()
            or not set(invocation.constraints.fixed_activity_ids) <= current.keys()
            or not set(invocation.constraints.user_authorizations) <= current.keys()):
        problems.append(issue("baseline_mismatch", "workflow_input.current_plan", "活动或锁定/授权ID与正式基线不一致"))
    else:
        for activity in input_activities:
            for source, target in (("start_time", "start_at"), ("end_time", "end_at")):
                timestamp = _timestamp(getattr(activity, source), activity_id=activity.activity_id,
                                       dates=context.activity_dates, tz=tz, field=f"current_plan.{activity.activity_id}.{source}", trip=trip)
                if timestamp != getattr(current[activity.activity_id], target):
                    problems.append(issue("baseline_mismatch", f"current_plan.{activity.activity_id}.{source}", "A输入不是当前正式快照"))
    incoming_events = [event.event_id for event in invocation.active_events]
    if len(incoming_events) != len(set(incoming_events)) or len(output.event_ids) != len(set(output.event_ids)):
        problems.append(issue("duplicate_event_id", "event_ids", "异常ID不得重复"))
    if set(incoming_events) != set(output.event_ids):
        problems.append(issue("event_set_mismatch", "event_ids", "输出必须覆盖本次调用的全部有效异常"))
    backend_events = {event.event_id for event in trip.events if event.active}
    bindings = context.event_bindings
    if (bindings.keys() != set(incoming_events) or set(bindings.values()) != backend_events
            or len(bindings.values()) != len(set(bindings.values()))):
        problems.append(issue("event_binding_mismatch", "context.event_bindings", "须将A事件逐一明确绑定到全部当前B有效事件，不能推断类型"))
    if output.official_version_unchanged is not True:
        problems.append(issue("official_version_changed", "official_version_unchanged", "模型不得声称已修改正式版本"))
    return problems


def _candidate_plan(bundle, option, support, tz):
    trip = bundle.context.trip
    baseline = trip.current_plan.plan
    previous = {a.id: a for a in baseline.activities}
    rows = option.proposed_schedule
    problems = []
    if not rows or len({row.activity_id for row in rows}) != len(rows):
        return None, [issue("invalid_schedule", "proposed_schedule", "完整候选至少含一个活动，活动ID不能重复")]
    missing = previous.keys() - {row.activity_id for row in rows}
    if missing != set(support.removed_activity_ids) or len(support.removed_activity_ids) != len(set(support.removed_activity_ids)):
        problems.append(issue("unexplained_activity_removal", "support.removed_activity_ids", "省略原活动须明确声明删除；proposed_schedule不是增量补丁"))
    if support.charges is None or support.refunds is None:
        problems.append(issue("missing_financial_snapshot", "support.charges/refunds", "须明确提供完整支出和退款流水，额外估算不等于完整费用"))
    if (trip.constraints.return_deadline is not None or baseline.arrival_at_return_station is not None) and support.arrival_at_return_station is None:
        problems.append(issue("missing_return_arrival", "support.arrival_at_return_station", "须提供候选到站时间，不能沿用旧到站预测或当作完整返程结束"))
    dates = {**bundle.context.activity_dates, **support.activity_dates}
    activities = []
    evidence = {key: value for key, value in baseline.activity_evidence.items() if key not in missing}
    original_predecessors = {a.id: baseline.activities[i - 1].id if i else None for i, a in enumerate(baseline.activities)}
    for index, row in enumerate(rows):
        field = f"proposed_schedule.{row.activity_id}"
        try:
            start = _timestamp(row.start_time, activity_id=row.activity_id, dates=dates, tz=tz, field=field + ".start_time", trip=trip)
            end = _timestamp(row.end_time, activity_id=row.activity_id, dates=dates, tz=tz, field=field + ".end_time", trip=trip)
            original = previous.get(row.activity_id)
            if (row.action == "new_candidate") != (original is None):
                raise ConversionProblem("invalid_action", field + ".action", "新增活动须用新ID；keep/reschedule必须引用正式活动")
            if row.action == "keep" and (start, end) != (original.start_at, original.end_at):
                raise ConversionProblem("invalid_action", field + ".action", "keep不能修改正式时段")
            supplied = support.activities.get(row.activity_id)
            previous_id = rows[index - 1].activity_id if index else None
            original_predecessor = previous.get(original_predecessors.get(row.activity_id))
            candidate_predecessor = support.activities.get(previous_id) or previous.get(previous_id)
            predecessor_changed = (original_predecessors.get(row.activity_id) != previous_id
                                   or (original_predecessor is not None and candidate_predecessor is not None
                                       and original_predecessor.poi_id != candidate_predecessor.poi_id))
            changed = original is None or (start, end) != (original.start_at, original.end_at)
            if supplied is None and (changed or predecessor_changed):
                raise ConversionProblem("missing_activity_details", f"support.activities.{row.activity_id}", "新增/调整活动或变化路段缺少明确POI、时段、开放/预约及交通资料")
            activity = supplied or original
            if activity.id != row.activity_id or (activity.start_at, activity.end_at) != (start, end):
                raise ConversionProblem("activity_details_mismatch", f"support.activities.{row.activity_id}", "支持资料的稳定ID和完整时段须与候选一致")
            if row.action == "keep" and activity.poi_id != original.poi_id:
                raise ConversionProblem("invalid_action", field + ".action", "keep不能通过支持资料更换原活动POI")
            if activity != original or predecessor_changed:
                evidence.pop(row.activity_id, None)
            activities.append(activity)
        except ConversionProblem as error:
            problems.append(error.issue)
    if problems:
        return None, problems
    ledger_ids = {x.id for x in [*support.charges, *support.refunds]}
    financial_evidence = {key: value for key, value in baseline.financial_evidence.items() if key in ledger_ids}
    try:
        candidate = TravelPlan(
            activities=activities, charges=support.charges, refunds=support.refunds,
            arrival_at_return_station=support.arrival_at_return_station,
            activity_evidence={**evidence, **support.activity_evidence},
            financial_evidence={**financial_evidence, **support.financial_evidence},
        )
    except ValidationError as error:
        return None, _validation_issues(error, "invalid_candidate")
    return candidate, []


def _validation_issues(error, code):
    return [issue(code, ".".join(map(str, item["loc"])), item["msg"]) for item in error.errors()]


def _adapt_option(bundle, raw, duplicates, tz):
    option_id = raw.get("option_id")
    candidate = None
    problems = []
    try:
        option = WFOption.model_validate(raw)
        if option.option_id in duplicates:
            raise ConversionProblem("duplicate_option_id", "option_id", "同一输出内option_id必须唯一")
        support = CandidateSupport.model_validate(bundle.context.option_support.get(option.option_id, {}))
        candidate, problems = _candidate_plan(bundle, option, support, tz)
    except ValidationError as error:
        problems = _validation_issues(error, "invalid_option_or_support")
    except ConversionProblem as error:
        problems = [error.issue]
    trip = bundle.context.trip
    required_pois = {a.poi_id for v in bundle.context.versions for a in v.plan.activities if a.booking_required}
    evaluation = evaluate_replan(baseline=trip.current_plan.plan, candidate=candidate, constraints=trip.constraints,
                                 events=trip.events, locked_activity_ids=trip.locked_activity_ids,
                                 required_booking_pois=required_pois)
    if candidate is not None:
        indexed = {a.id: a for a in candidate.activities}
        changed = {a.id for a in trip.current_plan.plan.activities if indexed.get(a.id) != a}
        if evaluation["locked_activity_violations"] is not None:
            changed.update(evaluation["locked_activity_violations"])
        for key in sorted(set(trip.locked_activity_ids) & changed):
            problems.append(issue("locked_activity_changed", f"activities.{key}", "A的任何授权都不能解除B的历史锁定"))
        fixed = (set(bundle.workflow_input.constraints.fixed_activity_ids)
                 | {a.activity_id for a in bundle.workflow_input.current_plan.activities if a.fixed}
                 | {a.id for a in trip.current_plan.plan.activities if a.booking_required and a.booking_status == "confirmed"})
        for key in sorted((fixed - set(trip.locked_activity_ids)) & changed):
            authorized = key in bundle.workflow_input.constraints.user_authorizations
            problems.append(issue("fixed_reschedule_unsupported" if authorized else "fixed_activity_unauthorized",
                                  f"activities.{key}", "未来固定活动调整需协调支持，授权不代表预约改签成功"))
        if evaluation["candidate_validation_status"] != "PASS":
            problems.append(issue("backend_validation_" + evaluation["candidate_validation_status"].lower(),
                                  "candidate.validation", "B端确定性核验未通过，不能进入可确认流程"))
        if bundle.workflow_output.draft_status == "needs_information" or option.feasibility == "conditional" or option.requires_external_actions:
            problems.append(issue("unresolved_analysis", "analysis", "A仍有待补信息、条件或外部待办，保留分析但不生成草案请求"))
        constraints = bundle.workflow_input.constraints
        if constraints.return_deadline is not None or constraints.return_deadline_hard is True:
            problems.append(issue("return_deadline_semantics_unresolved", "constraints.return_deadline",
                                  "A的返程完成严格早于截止与B的到站<=截止含义不同，不能自动互换"))
    rejected_codes = {"invalid_option_or_support", "invalid_candidate", "duplicate_option_id", "invalid_schedule",
                      "invalid_time", "time_outside_trip", "invalid_action", "activity_details_mismatch",
                      "unexplained_activity_removal", "locked_activity_changed", "fixed_activity_unauthorized", "backend_validation_fail"}
    status = ("rejected" if any(p["code"] in rejected_codes for p in problems)
              else "needs_information" if problems else "successfully_adapted")
    request = None
    if status == "successfully_adapted":
        identity = {"trip_id": trip.trip_id, "source_draft_id": bundle.workflow_output.draft_id,
                    "option_id": option_id, "version": trip.current_version, "event_revision": trip.event_revision,
                    "history_revision": trip.history_revision, "plan": candidate.model_dump(mode="json")}
        digest = sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:40]
        request = CreateDraft(request_id=f"wf-{digest}-create", draft_id=f"wf-{digest}",
                              base_version=trip.current_version, event_revision=trip.event_revision,
                              history_revision=trip.history_revision, plan=candidate,
                              handled_event_ids=sorted(bundle.context.event_bindings.values())).model_dump(mode="json")
    return {"option_id": option_id, "status": status, "issues": [{**p, "option_id": option_id} for p in problems],
            "analysis": deepcopy(raw), "candidate_plan": candidate.model_dump(mode="json") if candidate else None,
            "draft_request": request, "evaluation": evaluation}


def adapt_replan(bundle, *, measure=False):
    """Deterministic by default. Opt-in per-option timing covers local conversion/checks only."""
    try:
        parsed = SimulationBundle.model_validate(bundle)
        tz = _timezone(parsed.context.timezone_offset)
        problems = _context_issues(parsed, tz)
    except ValidationError as error:
        return {"status": "rejected", "issues": _validation_issues(error, "invalid_bundle"), "options": [], "analysis": deepcopy(bundle)}
    except ConversionProblem as error:
        missing = error.issue["code"].startswith("missing_")
        return {"status": "needs_information" if missing else "rejected", "issues": [error.issue], "options": [], "analysis": deepcopy(bundle)}
    analysis = {"workflow_input": deepcopy(bundle["workflow_input"]),
                "workflow_output": {key: deepcopy(value) for key, value in bundle["workflow_output"].items() if key != "options"}}
    if problems:
        return {"status": "rejected", "issues": problems, "options": [], "analysis": analysis}
    rows = parsed.workflow_output.options
    if not rows:
        return {"status": "needs_information", "issues": [issue("no_safe_options", "options", "A未给出安全候选，保留空列表")],
                "options": [], "analysis": analysis}
    counts = Counter(row.get("option_id") for row in rows if isinstance(row.get("option_id"), str))
    duplicates = {key for key, count in counts.items() if count > 1}
    options = []
    for row in rows:
        start = perf_counter_ns() if measure else None
        converted = _adapt_option(parsed, row, duplicates, tz)
        if measure:
            converted["evaluation"]["adapter_elapsed_ms"] = str(Decimal(perf_counter_ns() - start) / Decimal(1_000_000))
        options.append(converted)
    statuses = {option["status"] for option in options}
    status = ("successfully_adapted" if "successfully_adapted" in statuses
              else "needs_information" if "needs_information" in statuses else "rejected")
    return {"status": status, "issues": [], "options": options, "analysis": analysis}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Local WF_Replan simulation adapter; no API or database writes")
    parser.add_argument("input", type=Path)
    parser.add_argument("--measure", action="store_true", help="include non-reproducible local per-option timing, never AgentArts latency")
    args = parser.parse_args()
    result = adapt_replan(json.loads(args.input.read_text(encoding="utf-8")), measure=args.measure)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
