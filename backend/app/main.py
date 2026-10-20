import os
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException

from .logic import calculate_budget, validate_plan
from .schemas import BudgetRequest, BudgetResult, ValidatePlanRequest, ValidatePlanResult
from .travel_api import router as travel_router
from .travel_store import TravelStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    default_path = Path(__file__).resolve().parents[1] / "travelguard.local.sqlite3"
    app.state.travel_store = TravelStore(os.getenv("TRAVELGUARD_DB_PATH", str(default_path)))
    app.state.travel_store.initialize()
    yield


app = FastAPI(title="TravelGuard Backend", version="0.2.0", lifespan=lifespan)


def require_tool_key(x_tool_key: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("TRAVELGUARD_TOOL_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="工具服务尚未配置认证密钥")
    if x_tool_key is None or not compare_digest(x_tool_key, expected):
        raise HTTPException(status_code=401, detail="工具认证失败")


app.include_router(travel_router, dependencies=[Depends(require_tool_key)])


@app.get("/health")
def health():
    return {"status": "ok", "service": "travelguard-backend"}


@app.post(
    "/api/tools/calculate-budget",
    response_model=BudgetResult,
    dependencies=[Depends(require_tool_key)],
)
def budget(body: BudgetRequest):
    return calculate_budget(body)


@app.post(
    "/api/tools/validate-plan",
    response_model=ValidatePlanResult,
    dependencies=[Depends(require_tool_key)],
)
def verify(body: ValidatePlanRequest):
    return validate_plan(body)
