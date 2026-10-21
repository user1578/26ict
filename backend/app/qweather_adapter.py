"""QWeather Daily Forecast v1, with a small explicit outdoor screening policy."""

from datetime import datetime, time, timedelta, timezone
import math
import os
import re

from pydantic import ValidationError

from .external_schemas import ToolResult, WeatherData, WeatherRequest
from .provider_http import ProviderFailure, ProviderHTTP, unknown, utc_now
from .schemas import Status
from .travel_schemas import require_timezone

CHINA_TIME = timezone(timedelta(hours=8))
HOST_PATTERN = re.compile(r"[a-z0-9-]+\.qweatherapi\.com", re.ASCII)
# v1 codes are not contiguous. New codes remain UNKNOWN until explicitly supported.
# https://dev.qweather.com/en/docs/api/weather/weather-conditions/
KNOWN_CONDITION_CODES = frozenset(str(code) for code in (
    *range(100, 105), *range(300, 319), 399, *range(400, 411), 499,
    *range(500, 505), *range(507, 516), 900, 901,
))


def quantity(value, unit, *, nonnegative=False):
    if value["unit"] != unit or isinstance(value["value"], bool):
        raise ValueError("unexpected unit")
    result = float(value["value"])
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError("invalid quantity")
    return result


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require_timezone(result)
    return result


class QWeatherAdapter:
    def __init__(self, http: ProviderHTTP):
        self.http = http

    def get_weather_risk(self, body: WeatherRequest):
        source_ref = None
        try:
            today = utc_now().astimezone(CHINA_TIME).date()
            if not 0 <= (body.on_date - today).days < 7:
                raise ProviderFailure("forecast_out_of_range", "当前工具仅支持中国时区今天起7日内预报，不补造远期或历史天气")
            key = os.getenv("QWEATHER_API_KEY", "").strip()
            host = os.getenv("QWEATHER_API_HOST", "").strip().lower()
            if not key or not host:
                raise ProviderFailure("missing_credentials", "尚未配置和风天气QWEATHER_API_KEY及QWEATHER_API_HOST")
            if not HOST_PATTERN.fullmatch(host):
                raise ProviderFailure("invalid_configuration", "QWEATHER_API_HOST须为控制台提供的*.qweatherapi.com域名，不含协议或路径")
            source_ref = f"https://{host}/weather/v1/daily/{body.location.latitude:.6f}/{body.location.longitude:.6f}"
            result = self.http.get(source_ref, params={"days": 7, "localTime": "true", "lang": "zh"},
                                   headers={"X-QW-Api-Key": key})
            days = result["days"]
            if not isinstance(days, list):
                raise ValueError("invalid days")
            matches = [day for day in days if timestamp(day["daytime"]["forecastStartTime"])
                       .astimezone(CHINA_TIME).date() == body.on_date]
            if len(matches) != 1:
                raise ProviderFailure("forecast_missing", "来源中没有目标日期的唯一预报，不能推算或沿用其他日期")
            day = matches[0]
            start, end = timestamp(day["forecastStartTime"]), timestamp(day["forecastEndTime"])
            if end - start != timedelta(days=1) or not start <= timestamp(day["daytime"]["forecastStartTime"]) < end:
                raise ValueError("invalid period")
            periods = [day["daytime"], day["nighttime"]]
            morning = datetime.combine(body.on_date, time(7), CHINA_TIME)
            evening = datetime.combine(body.on_date, time(19), CHINA_TIME)
            expected_periods = [(morning, evening), (evening, morning + timedelta(days=1))]
            for period, (expected_start, expected_end) in zip(periods, expected_periods):
                if (timestamp(period["forecastStartTime"]) != expected_start
                        or timestamp(period["forecastEndTime"]) != expected_end):
                    raise ValueError("mismatched day/night forecast period")
            high = quantity(day["temperatureMax"], "°C")
            low = quantity(day["temperatureMin"], "°C")
            if high < low:
                raise ValueError("temperature order")
            precip = sum(quantity(p["precipitation"]["amount"], "mm", nonnegative=True) for p in periods)
            wind = max(quantity(p["wind"]["speed"], "m/s", nonnegative=True) for p in periods)
            codes = [p["condition"]["code"] for p in periods]
            texts = [p["condition"]["text"] for p in periods]
            if (any(not isinstance(t, str) or not t.strip() for t in texts)
                    or any(not isinstance(c, str) or c not in KNOWN_CONDITION_CODES for c in codes)):
                raise ValueError("unknown conditions")
            factors = []
            if high >= 35:
                factors.append("high_temperature")
            if low <= 0:
                factors.append("freezing_temperature")
            if precip >= 10:
                factors.append("precipitation")
            if wind >= 10.8:
                factors.append("strong_wind")
            if any(str(c) in {"302", "303", "304"} or str(c).startswith("4") for c in codes):
                factors.append("thunder_or_snow")
            risk = Status.NOT_APPLICABLE if body.activity_type == "indoor" else (Status.FAIL if factors else Status.PASS)
            attributions = result["metadata"]["attributions"]
            if not isinstance(attributions, list) or not all(isinstance(a, str) for a in attributions):
                raise ValueError("invalid attribution")
            data = WeatherData(on_date=body.on_date, forecast_start_at=start, forecast_end_at=end,
                               temperature_max_c=high, temperature_min_c=low, precipitation_mm=precip,
                               max_wind_speed_mps=wind, conditions=texts, risk_check=risk, risk_factors=factors)
            return ToolResult(status="PASS", code="ok", message="已取得逐日预报；活动风险为本地阈值推导",
                              evidence=self.http.evidence("qweather", source_ref, attributions=attributions), data=data)
        except ProviderFailure as failure:
            return unknown("qweather", source_ref, failure)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError, ValidationError):
            return unknown("qweather", source_ref, ProviderFailure("invalid_provider_data", "和风天气预报字段缺失、单位异常或格式错误"))
