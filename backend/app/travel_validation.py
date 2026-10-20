"""Deterministic checks against persisted constraints, facts, and active events."""

from .logic import validate_plan
from .schemas import BudgetRequest, Check, Status, ValidatePlanRequest, ValidatePlanResult
from .travel_schemas import EventView, TravelPlan, TripConstraints


def budget_input(plan: TravelPlan, constraints: TripConstraints) -> BudgetRequest:
    return BudgetRequest(budget_cny=constraints.budget_cny, charges=plan.charges, refunds=plan.refunds)


def validate_snapshot(
    plan: TravelPlan,
    constraints: TripConstraints,
    events: list[EventView],
    locked_ids: list[str],
    previous: TravelPlan | None = None,
    required_booking_pois: set[str] | None = None,
) -> ValidatePlanResult:
    locked = [a for a in previous.activities if a.id in locked_ids] if previous else []
    result = validate_plan(ValidatePlanRequest(
        activities=plan.activities, budget=budget_input(plan, constraints),
        max_walking_minutes_per_leg=constraints.max_walking_minutes_per_leg,
        return_deadline=constraints.return_deadline,
        arrival_at_return_station=plan.arrival_at_return_station,
        locked_activities=locked,
    ))

    def add(name: str, status: Status, detail: str) -> None:
        result.checks.append(Check(name=name, status=status, detail=detail))

    missing = [a.id for a in plan.activities
               if (a.opening_status == "confirmed_open"
                   or (a.booking_required and a.booking_status == "confirmed"))
               and a.id not in plan.activity_evidence]
    missing += [x.id for x in [*plan.charges, *plan.refunds]
                if x.status in ("paid", "received") and x.id not in plan.financial_evidence]
    add("evidence_check", Status.UNKNOWN if missing else Status.PASS,
        f"缺少事实证据引用：{','.join(missing)}" if missing else "声明的已核实事实均有调用方提供的证据引用")

    if previous:
        old_facts = {x.id: x for x in [*previous.charges, *previous.refunds]
                     if x.status in ("paid", "received")}
        new_facts = {x.id: x for x in [*plan.charges, *plan.refunds]
                     if x.status in ("paid", "received")}
        immutable = old_facts == new_facts and all(
            plan.financial_evidence.get(key) == previous.financial_evidence.get(key) for key in old_facts
        )
        add("financial_state_check", Status.PASS if immutable else Status.FAIL,
            "已支付费用和已到账退款保持不变；方案不会执行资金操作" if immutable
            else "草案不得新增、删除或修改已支付/已到账事实及证据")
        unchanged_evidence = all(plan.activity_evidence.get(key) == previous.activity_evidence.get(key)
                                 for key in locked_ids)
        add("locked_evidence_check", Status.PASS if unchanged_evidence else Status.FAIL,
            "锁定历史活动证据保持不变" if unchanged_evidence else "锁定历史活动证据被修改")

        prior_activities = {a.id: a for a in previous.activities}
        booking_claims = []
        for activity in plan.activities:
            if activity.booking_status != "confirmed":
                continue
            original = prior_activities.get(activity.id)
            if (original is None or original.booking_status != "confirmed"
                    or (activity.poi_id, activity.start_at, activity.end_at) != (
                        original.poi_id, original.start_at, original.end_at)
                    or plan.activity_evidence.get(activity.id) != previous.activity_evidence.get(activity.id)):
                booking_claims.append(activity.id)
        required_pois = required_booking_pois or {a.poi_id for a in previous.activities if a.booking_required}
        downgraded = [a.id for a in plan.activities if a.poi_id in required_pois and not a.booking_required]
        add("booking_state_check", Status.FAIL if booking_claims or downgraded else Status.PASS,
            "草案不能宣称新预约/改期已完成，或降低已知地点预约要求" if booking_claims or downgraded
            else "未新增预约完成事实，保留已知预约要求；未执行取消或改签")

    # A return estimate cannot contradict the last activity, even if both precede the deadline.
    if plan.arrival_at_return_station is not None:
        consistent = plan.arrival_at_return_station >= max(a.end_at for a in plan.activities)
        add("return_timeline_check", Status.PASS if consistent else Status.FAIL,
            "返程到站时间不早于行程结束" if consistent else "返程到站时间早于行程结束")

    indexed = {a.id: a for a in plan.activities}
    for event in events:
        if not event.active:
            continue
        if event.verification_status != "verified":
            add(f"event:{event.event_id}:evidence", Status.UNKNOWN, "异常事实尚未核实")
        if event.kind == "train_delay":
            target = indexed.get(event.activity_id)
            satisfied = target is not None and target.start_at >= event.earliest_start_at
            # Keeping the target identity prevents silently deleting the delayed journey.
            if previous and target is not None:
                original = next((a for a in previous.activities if a.id == event.activity_id), None)
                satisfied = satisfied and original is not None and target.poi_id == original.poi_id
            add(f"event:{event.event_id}", Status.PASS if satisfied else Status.FAIL,
                "已遵守晚点后的最早开始时间" if satisfied else "晚点活动被删除、替换或安排过早")
        else:
            conflicts = [a.id for a in plan.activities
                         if a.poi_id == event.poi_id and a.end_at > event.effective_at]
            add(f"event:{event.event_id}", Status.FAIL if conflicts else Status.PASS,
                f"关闭生效后仍安排该地点：{','.join(conflicts)}" if conflicts else "关闭生效后未安排该地点")

    statuses = {check.status for check in result.checks}
    result.overall = (Status.FAIL if Status.FAIL in statuses
                      else Status.UNKNOWN if Status.UNKNOWN in statuses else Status.PASS)
    result.note = "仅核验持久化约束及调用方提供的事实/证据引用；模拟证据不代表真实服务状态，未联网核实或执行第三方交易。"
    return result
