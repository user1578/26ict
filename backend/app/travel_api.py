from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from .travel_schemas import (
    ID_PATTERN, ConfirmDraft, CreateDraft, CreateTrip, DraftView, EventView,
    LockActivities, PutEvent, TripView, VersionView,
)
from .travel_store import TravelStore


router = APIRouter(prefix="/api/trips", tags=["旅行状态与版本"])
PathId = Annotated[str, Path(min_length=1, max_length=128, pattern=ID_PATTERN)]


def store(request: Request) -> TravelStore:
    return request.app.state.travel_store


Store = Annotated[TravelStore, Depends(store)]


@router.post("", response_model=TripView, status_code=201)
def create_trip(body: CreateTrip, state: Store):
    return state.create_trip(body)


@router.get("/{trip_id}", response_model=TripView)
def get_trip(trip_id: PathId, state: Store):
    return state.get_trip(trip_id)


@router.get("/{trip_id}/versions", response_model=list[VersionView])
def get_versions(trip_id: PathId, state: Store):
    return state.get_versions(trip_id)


@router.put("/{trip_id}/events/{event_id}", response_model=EventView)
def put_event(trip_id: PathId, event_id: PathId, body: PutEvent, state: Store):
    return state.put_event(trip_id, event_id, body)


@router.post("/{trip_id}/drafts", response_model=DraftView, status_code=201)
def create_draft(trip_id: PathId, body: CreateDraft, state: Store):
    return state.create_draft(trip_id, body)


@router.get("/{trip_id}/drafts", response_model=list[DraftView])
def get_drafts(trip_id: PathId, state: Store):
    return state.get_drafts(trip_id)


@router.get("/{trip_id}/drafts/{draft_id}", response_model=DraftView)
def get_draft(trip_id: PathId, draft_id: PathId, state: Store):
    return state.get_draft(trip_id, draft_id)


@router.post("/{trip_id}/drafts/{draft_id}/confirm", response_model=VersionView)
def confirm_draft(trip_id: PathId, draft_id: PathId, body: ConfirmDraft, state: Store):
    return state.confirm_draft(trip_id, draft_id, body)


@router.post("/{trip_id}/locks", response_model=TripView)
def lock_activities(trip_id: PathId, body: LockActivities, state: Store):
    return state.lock_activities(trip_id, body)
