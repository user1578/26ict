"""Bounded HTTP access. Never return provider errors/URLs containing credentials."""

from datetime import datetime, timezone
from typing import Literal

import httpx

from .external_schemas import Evidence, ToolResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderFailure(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ProviderHTTP:
    def __init__(self, client: httpx.Client, *, data_type: Literal["real", "simulated"] = "real"):
        self.client = client
        self.data_type = data_type

    def get(self, url: str, *, params=None, headers=None) -> dict:
        try:
            response = self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise ProviderFailure("provider_timeout", "外部服务请求超时，请稍后重试") from None
        except httpx.HTTPStatusError:
            raise ProviderFailure("provider_unavailable", "外部服务拒绝请求或暂不可用") from None
        except httpx.RequestError:
            raise ProviderFailure("provider_unavailable", "无法连接外部服务") from None
        try:
            # Explicitly reject known stale cached responses; no stale fallback or local cache.
            age = float(response.headers.get("Age", "0"))
            if age < 0 or not age < 3600:
                raise ProviderFailure("stale_data", "来源缓存数据已过期")
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("not an object")
            return result
        except (ValueError, TypeError):
            raise ProviderFailure("invalid_provider_data", "外部服务返回了无法核验的数据结构") from None

    def evidence(self, source, source_ref, **kwargs) -> Evidence:
        return Evidence(source=source, source_ref=source_ref, fetched_at=utc_now(),
                        data_type=self.data_type,
                        verification_status="source_reported" if self.data_type == "real" else "unverified",
                        **kwargs)


def unknown(source, source_ref, failure: ProviderFailure) -> ToolResult:
    return ToolResult(status="UNKNOWN", code=failure.code, message=failure.message,
                      evidence=Evidence(source=source, source_ref=source_ref, fetched_at=utc_now()))
