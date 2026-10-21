from decimal import Decimal

from .schemas import (
    BudgetRequest,
    BudgetResult,
    Check,
    Status,
    ValidatePlanRequest,
    ValidatePlanResult,
)

ZERO = Decimal("0.00")


def calculate_budget(data: BudgetRequest) -> BudgetResult:
    paid = sum((x.amount_cny for x in data.charges if x.status == "paid"), ZERO)
    planned = sum((x.amount_cny for x in data.charges if x.status == "planned"), ZERO)
    received = sum((x.amount_cny for x in data.refunds if x.status == "received"), ZERO)
    pending = sum((x.amount_cny for x in data.refunds if x.status == "pending"), ZERO)
    # 尚未到账的退款不得抵扣可用预算。
    total = paid + planned - received
    return BudgetResult(
        budget_cny=data.budget_cny,
        paid_cny=paid,
        planned_cny=planned,
        received_refunds_cny=received,
        pending_refunds_cny=pending,
        conservative_total_cny=total,
        remaining_cny=data.budget_cny - total,
        within_budget=total <= data.budget_cny,
    )


def validate_plan(data: ValidatePlanRequest) -> ValidatePlanResult:
    checks: list[Check] = []

    def add(name: str, status: Status, detail: str) -> None:
        checks.append(Check(name=name, status=status, detail=detail))

    acts = data.activities
    if any(acts[i].start_at < acts[i - 1].start_at for i in range(1, len(acts))):
        add("time_check", Status.FAIL, "活动未按时间先后排列")
    elif any(acts[i].start_at < acts[i - 1].end_at for i in range(1, len(acts))):
        add("time_check", Status.FAIL, "存在活动时间重叠")
    elif any(
        acts[i].transport_minutes_from_previous is not None
        and (acts[i].start_at - acts[i - 1].end_at).total_seconds() < 60 * acts[i].transport_minutes_from_previous
        for i in range(1, len(acts))
    ):
        add("time_check", Status.FAIL, "活动间隔不足以完成已知交通时间")
    elif len(acts) > 1 and any(a.transport_minutes_from_previous is None for a in acts[1:]):
        add("time_check", Status.UNKNOWN, "缺少部分活动之间的交通耗时")
    else:
        add("time_check", Status.PASS, "已知活动时段与交通耗时没有冲突")

    openings = {x.opening_status for x in acts}
    if "confirmed_closed" in openings:
        add("opening_check", Status.FAIL, "包含已知关闭的地点")
    elif "unknown" in openings:
        add("opening_check", Status.UNKNOWN, "部分地点开放信息未核实")
    else:
        add("opening_check", Status.PASS, "输入的地点开放状态均为已核实开放")

    bookings = [a.booking_status for a in acts if a.booking_required]
    if not bookings:
        add("booking_check", Status.NOT_APPLICABLE, "没有要求核验的预约")
    elif "not_confirmed" in bookings:
        add("booking_check", Status.FAIL, "存在未确认的必需预约")
    elif "unknown" in bookings:
        add("booking_check", Status.UNKNOWN, "存在状态未知的必需预约")
    else:
        add("booking_check", Status.PASS, "输入的必需预约均已确认")

    if data.budget is None:
        add("budget_check", Status.UNKNOWN, "未提供完整费用记录和预算")
    else:
        budget = calculate_budget(data.budget)
        add(
            "budget_check",
            Status.PASS if budget.within_budget else Status.FAIL,
            f"保守预计总支出 {budget.conservative_total_cny} 元，预算 {budget.budget_cny} 元",
        )

    # 第一个活动没有“上一地点”，只核验后续活动之间的步行路段。
    legs = acts[1:]
    if data.max_walking_minutes_per_leg is None:
        add("walking_check", Status.NOT_APPLICABLE, "未设置单段步行硬限制")
    elif any(
        a.walking_minutes_from_previous is not None
        and a.walking_minutes_from_previous > data.max_walking_minutes_per_leg
        for a in legs
    ):
        add("walking_check", Status.FAIL, "部分步行路段超过限制")
    elif any(a.walking_minutes_from_previous is None for a in legs):
        add("walking_check", Status.UNKNOWN, "部分步行路段耗时未知")
    else:
        add("walking_check", Status.PASS, "已提供的步行路段均满足限制")

    if data.return_deadline is None:
        add("return_check", Status.NOT_APPLICABLE, "未设置返程硬截止时间")
    elif data.arrival_at_return_station is None:
        add("return_check", Status.UNKNOWN, "缺少到达返程车站的预计时间")
    else:
        on_time = data.arrival_at_return_station <= data.return_deadline
        add(
            "return_check",
            Status.PASS if on_time else Status.FAIL,
            "返程到站时间符合截止要求" if on_time else "预计抵达返程车站超过截止时间",
        )

    if data.arrival_at_return_station is not None:
        consistent = data.arrival_at_return_station >= max(a.end_at for a in acts)
        add("return_timeline_check", Status.PASS if consistent else Status.FAIL,
            "返程到站时间不早于行程结束" if consistent else "返程到站时间早于行程结束")

    if not data.locked_activities:
        add("state_check", Status.NOT_APPLICABLE, "未提供不可修改的历史活动")
    else:
        indexed = {x.id: x for x in acts}
        changed = [x.id for x in data.locked_activities if indexed.get(x.id) != x]
        add(
            "state_check",
            Status.FAIL if changed else Status.PASS,
            f"锁定活动被删除或修改：{','.join(changed)}" if changed else "锁定活动保持不变",
        )

    statuses = {x.status for x in checks}
    overall = (
        Status.FAIL if Status.FAIL in statuses
        else Status.UNKNOWN if Status.UNKNOWN in statuses
        else Status.PASS
    )
    return ValidatePlanResult(overall=overall, checks=checks)
