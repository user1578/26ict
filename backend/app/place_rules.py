"""Read a configured, curated rule book. No fabricated bundled place facts."""

from datetime import timedelta
import os
from pathlib import Path

from pydantic import ValidationError

from .external_schemas import Evidence, PlaceRules, PlaceRulesRequest, RuleBook, ToolResult
from .provider_http import ProviderFailure, unknown, utc_now


class LocalRuleStore:
    def get_place_rules(self, body: PlaceRulesRequest):
        path = os.getenv("TRAVELGUARD_RULES_PATH", "").strip()
        if not path:
            return unknown("local_rules", None, ProviderFailure("missing_rules_source", "尚未配置地点规则知识库TRAVELGUARD_RULES_PATH"))
        try:
            book = RuleBook.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))
        except OSError:
            return unknown("local_rules", None, ProviderFailure("rules_unavailable", "地点规则文件不存在或无法读取"))
        except (ValueError, ValidationError):
            return unknown("local_rules", None, ProviderFailure("invalid_rules_data", "地点规则文件结构或来源证据不完整"))
        # A short closure inside a longer opening interval must not disappear during filtering.
        overlapping = [record for record in book.records if record.poi_id == body.poi_id
                       and record.valid_from < body.visit_end_at and record.valid_until > body.visit_start_at]
        if len(overlapping) > 1:
            return unknown("local_rules", None, ProviderFailure("rules_conflict", "存在相互重叠的地点规则，请维护方核实"))
        if (not overlapping or overlapping[0].valid_from > body.visit_start_at
                or overlapping[0].valid_until < body.visit_end_at):
            return unknown("local_rules", None, ProviderFailure(
                "rules_not_found", "没有覆盖完整访问时段的地点规则"))
        record = overlapping[0]
        now = utc_now()
        evidence = Evidence(source="local_rules", source_ref=record.source_ref, fetched_at=now,
                            source_updated_at=record.retrieved_at, data_type=record.data_type,
                            verification_status=record.verification_status if record.data_type == "real" else "unverified")
        code, message = "ok", "规则覆盖指定访问时段；预约要求不等于用户预约已完成"
        if record.retrieved_at > now + timedelta(minutes=5) or now - record.retrieved_at > timedelta(days=7):
            code, message = "stale_rules", "规则采集时间异常或已超过7日，请重新核实"
        elif record.data_type != "real" or record.verification_status != "verified":
            code, message = "unverified_rules", "模拟或未经核实的规则不能作为真实开放/预约依据"
        elif (record.opening_status == "unknown" or record.booking_required is None
              or record.ticket_price_cny is None or (record.booking_required and not record.booking_note)):
            code, message = "incomplete_rules", "开放、预约或票价依据不完整；缺少信息不得视为不需要预约或免费"
        # Unsafe records are withheld rather than leaking confirmed_* values to consumers.
        data = PlaceRules.model_validate(record.model_dump(include=set(PlaceRules.model_fields))) if code == "ok" else None
        return ToolResult(status="PASS" if code == "ok" else "UNKNOWN", code=code, message=message,
                          evidence=evidence, data=data)
