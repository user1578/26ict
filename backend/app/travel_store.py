"""Single-node SQLite state machine. Every mutation and idempotency receipt is atomic."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from fastapi import HTTPException

from .logic import calculate_budget
from .schemas import Status
from .travel_schemas import (
    ConfirmDraft, CreateDraft, CreateTrip, DraftView, EventFacts, EventView,
    LockActivities, PutEvent, TravelPlan, TripConstraints, TripPreferences, VersionView,
)
from .travel_validation import budget_input, validate_snapshot


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def reject(code: str, message: str, status: int = 409) -> None:
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


class TravelStore:
    def __init__(self, path: str | Path):
        self.path = str(path)

    @contextmanager
    def transaction(self, *, write=False):
        # No shared connection or in-process mutex: SQLite serializes independent workers too.
        with closing(sqlite3.connect(self.path, timeout=5, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def initialize(self) -> None:
        # Schema changes and user_version advance atomically with the same worker write lock.
        with self.transaction(write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError(f"不支持的旅行数据库版本：{version}")
            statements = [
                """CREATE TABLE IF NOT EXISTS trips (
                    trip_id TEXT PRIMARY KEY, title TEXT NOT NULL, constraints_json TEXT NOT NULL,
                    current_version INTEGER NOT NULL CHECK(current_version >= 1),
                    event_revision INTEGER NOT NULL DEFAULT 0,
                    history_revision INTEGER NOT NULL DEFAULT 0, locked_ids_json TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS versions (
                    trip_id TEXT NOT NULL REFERENCES trips(trip_id), version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, PRIMARY KEY(trip_id, version))""",
                """CREATE TABLE IF NOT EXISTS events (
                    trip_id TEXT NOT NULL REFERENCES trips(trip_id), event_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, PRIMARY KEY(trip_id, event_id))""",
                """CREATE TABLE IF NOT EXISTS drafts (
                    trip_id TEXT NOT NULL REFERENCES trips(trip_id), draft_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','stale','committed')),
                    committed_version INTEGER, payload_json TEXT NOT NULL,
                    PRIMARY KEY(trip_id, draft_id),
                    FOREIGN KEY(trip_id, committed_version) REFERENCES versions(trip_id, version))""",
                """CREATE TABLE IF NOT EXISTS requests (
                    trip_id TEXT NOT NULL REFERENCES trips(trip_id), request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, response_json TEXT NOT NULL,
                    PRIMARY KEY(trip_id, request_id))""",
            ]
            for statement in statements:
                db.execute(statement)
            if version < 2:
                # Nullable additions leave every legacy value unknown; no snapshot/receipt rewrite.
                for column in ("city TEXT", "party_size INTEGER", "start_date TEXT", "end_date TEXT",
                               "preferences_json TEXT"):
                    db.execute(f"ALTER TABLE trips ADD COLUMN {column}")
                db.execute("PRAGMA user_version = 2")

    def _mutate(self, trip_id, operation, body, action):
        request_body = body.model_dump(mode="json")
        if isinstance(body, CreateTrip):
            # Keep normalized v1 create requests compatible with their persisted fingerprints.
            for field in ("city", "party_size", "start_date", "end_date"):
                if request_body[field] is None:
                    request_body.pop(field)
            if body.preferences.stay_together is None:
                request_body.pop("preferences")
        fingerprint = sha256(encode({"operation": operation, "body": request_body})
                             .encode("utf-8")).hexdigest()
        with self.transaction(write=True) as db:
            receipt = db.execute("SELECT * FROM requests WHERE trip_id=? AND request_id=?",
                                 (trip_id, body.request_id)).fetchone()
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    reject("idempotency_conflict", "同一旅行的request_id不能用于不同请求")
                return json.loads(receipt["response_json"])
            response = action(db)
            db.execute("INSERT INTO requests VALUES (?,?,?,?)",
                       (trip_id, body.request_id, fingerprint, encode(response)))
            return response

    @staticmethod
    def _trip(db, trip_id):
        trip = db.execute("SELECT * FROM trips WHERE trip_id=?", (trip_id,)).fetchone()
        if trip is None:
            reject("trip_not_found", "旅行不存在", 404)
        return trip

    @staticmethod
    def _version(db, trip_id, version):
        row = db.execute("SELECT payload_json FROM versions WHERE trip_id=? AND version=?",
                         (trip_id, version)).fetchone()
        if row is None:
            reject("version_not_found", "正式版本不存在", 404)
        return json.loads(row["payload_json"])

    @staticmethod
    def _events(db, trip_id):
        return [EventView.model_validate_json(row["payload_json"])
                for row in db.execute("SELECT payload_json FROM events WHERE trip_id=? ORDER BY event_id",
                                      (trip_id,))]

    @staticmethod
    def _draft(db, trip_id, draft_id):
        row = db.execute("SELECT * FROM drafts WHERE trip_id=? AND draft_id=?",
                         (trip_id, draft_id)).fetchone()
        if row is None:
            reject("draft_not_found", "草案不存在", 404)
        payload = json.loads(row["payload_json"])
        payload.update(status=row["status"], committed_version=row["committed_version"])
        return DraftView.model_validate(payload)

    def _view(self, db, trip_id):
        trip = self._trip(db, trip_id)
        return {
            "trip_id": trip_id, "title": trip["title"], "current_version": trip["current_version"],
            "city": trip["city"], "party_size": trip["party_size"],
            "start_date": trip["start_date"], "end_date": trip["end_date"],
            "preferences": (json.loads(trip["preferences_json"]) if trip["preferences_json"] is not None
                            else TripPreferences().model_dump(mode="json")),
            "event_revision": trip["event_revision"], "history_revision": trip["history_revision"],
            "constraints": json.loads(trip["constraints_json"]),
            "locked_activity_ids": json.loads(trip["locked_ids_json"]),
            "current_plan": self._version(db, trip_id, trip["current_version"]),
            "events": [event.model_dump(mode="json") for event in self._events(db, trip_id)],
        }

    @staticmethod
    def _check_tokens(trip, body):
        if (body.base_version, body.event_revision, body.history_revision) != (
            trip["current_version"], trip["event_revision"], trip["history_revision"]
        ):
            reject("revision_conflict", "正式版本、有效异常或锁定历史已变化，请重新读取旅行状态")

    @staticmethod
    def _stale_pending(db, trip_id):
        db.execute("UPDATE drafts SET status='stale' WHERE trip_id=? AND status='pending'", (trip_id,))

    def _evaluate(self, db, trip, plan):
        previous = TravelPlan.model_validate(self._version(db, trip["trip_id"], trip["current_version"])["plan"])
        # Omitting a visit in V2 must not erase its known booking requirement when re-added in V3.
        required_pois = {
            activity["poi_id"]
            for row in db.execute("SELECT payload_json FROM versions WHERE trip_id=?", (trip["trip_id"],))
            for activity in json.loads(row[0])["plan"]["activities"] if activity["booking_required"]
        }
        return validate_snapshot(
            plan, TripConstraints.model_validate_json(trip["constraints_json"]),
            self._events(db, trip["trip_id"]), json.loads(trip["locked_ids_json"]), previous, required_pois,
        )

    @staticmethod
    def _require_pass(validation):
        if validation.overall != Status.PASS:
            raise HTTPException(status_code=422, detail={
                "code": "verification_blocked", "message": "必须通过全部必要核验才能建立正式版本",
                "validation": validation.model_dump(mode="json"),
            })

    @staticmethod
    def _insert_version(db, trip_id, version, plan, constraints, validation,
                        event_revision, history_revision, draft_id=None, confirmation=None):
        result = VersionView(
            trip_id=trip_id, version=version, event_revision=event_revision,
            history_revision=history_revision, source_draft_id=draft_id, plan=plan,
            budget=calculate_budget(budget_input(plan, constraints)), validation=validation,
            confirmation=confirmation, created_at=datetime.now(timezone.utc),
        ).model_dump(mode="json")
        db.execute("INSERT INTO versions VALUES (?,?,?)", (trip_id, version, encode(result)))
        return result

    def create_trip(self, body: CreateTrip):
        def action(db):
            if db.execute("SELECT 1 FROM trips WHERE trip_id=?", (body.trip_id,)).fetchone():
                reject("trip_exists", "旅行ID已存在")
            constraints = TripConstraints.model_validate(body.model_dump(include=set(TripConstraints.model_fields)))
            validation = validate_snapshot(body.plan, constraints, [], [])
            self._require_pass(validation)
            db.execute("INSERT INTO trips (trip_id,title,constraints_json,current_version,event_revision,"
                       "history_revision,locked_ids_json,city,party_size,start_date,end_date,preferences_json) "
                       "VALUES (?,?,?,1,0,0,?,?,?,?,?,?)",
                       (body.trip_id, body.title, constraints.model_dump_json(), encode(body.locked_activity_ids),
                        body.city, body.party_size, body.start_date.isoformat() if body.start_date else None,
                        body.end_date.isoformat() if body.end_date else None, body.preferences.model_dump_json()))
            self._insert_version(db, body.trip_id, 1, body.plan, constraints, validation, 0, 0)
            return self._view(db, body.trip_id)
        return self._mutate(body.trip_id, "create_trip", body, action)

    def get_trip(self, trip_id):
        with self.transaction() as db:
            return self._view(db, trip_id)

    def get_versions(self, trip_id):
        with self.transaction() as db:
            self._trip(db, trip_id)
            return [json.loads(row["payload_json"])
                    for row in db.execute("SELECT payload_json FROM versions WHERE trip_id=? ORDER BY version",
                                          (trip_id,))]

    def get_draft(self, trip_id, draft_id):
        with self.transaction() as db:
            self._trip(db, trip_id)
            return self._draft(db, trip_id, draft_id).model_dump(mode="json")

    def get_drafts(self, trip_id):
        with self.transaction() as db:
            self._trip(db, trip_id)
            ids = [row[0] for row in db.execute("SELECT draft_id FROM drafts WHERE trip_id=? ORDER BY draft_id",
                                              (trip_id,))]
            return [self._draft(db, trip_id, draft_id).model_dump(mode="json") for draft_id in ids]

    def put_event(self, trip_id, event_id, body: PutEvent):
        def action(db):
            trip = self._trip(db, trip_id)
            if body.expected_event_revision != trip["event_revision"]:
                reject("revision_conflict", "异常修订号已变化")
            facts = EventFacts.model_validate(body.model_dump(include=set(EventFacts.model_fields)))
            if facts.active and facts.kind == "train_delay":
                current = self._version(db, trip_id, trip["current_version"])
                if facts.activity_id not in {a["id"] for a in current["plan"]["activities"]}:
                    reject("invalid_event_target", "晚点异常必须引用当前正式行程中的活动", 422)
            old = db.execute("SELECT payload_json FROM events WHERE trip_id=? AND event_id=?",
                             (trip_id, event_id)).fetchone()
            if old:
                previous = EventView.model_validate_json(old[0])
                if facts.model_dump() == previous.model_dump(include=set(EventFacts.model_fields)):
                    return previous.model_dump(mode="json")
            revision = trip["event_revision"] + 1
            result = EventView(**facts.model_dump(), event_id=event_id, revision=revision).model_dump(mode="json")
            db.execute("INSERT INTO events VALUES (?,?,?) ON CONFLICT(trip_id,event_id) "
                       "DO UPDATE SET payload_json=excluded.payload_json", (trip_id, event_id, encode(result)))
            db.execute("UPDATE trips SET event_revision=? WHERE trip_id=?", (revision, trip_id))
            self._stale_pending(db, trip_id)
            return result
        return self._mutate(trip_id, f"put_event:{event_id}", body, action)

    def create_draft(self, trip_id, body: CreateDraft):
        def action(db):
            trip = self._trip(db, trip_id)
            self._check_tokens(trip, body)
            active = {event.event_id for event in self._events(db, trip_id) if event.active}
            if active != set(body.handled_event_ids):
                reject("event_set_conflict", "草案必须声明当前全部有效异常，不能遗漏或带入无效异常")
            if db.execute("SELECT 1 FROM drafts WHERE trip_id=? AND draft_id=?",
                          (trip_id, body.draft_id)).fetchone():
                reject("draft_exists", "草案ID已存在，请使用新ID")
            result = DraftView(
                trip_id=trip_id, draft_id=body.draft_id, base_version=body.base_version,
                event_revision=body.event_revision, history_revision=body.history_revision,
                handled_event_ids=sorted(active), status="pending", committed_version=None,
                plan=body.plan, validation=self._evaluate(db, trip, body.plan), created_at=datetime.now(timezone.utc),
            ).model_dump(mode="json")
            db.execute("INSERT INTO drafts VALUES (?,?,'pending',NULL,?)", (trip_id, body.draft_id, encode(result)))
            return result
        return self._mutate(trip_id, "create_draft", body, action)

    def confirm_draft(self, trip_id, draft_id, body: ConfirmDraft):
        def action(db):
            trip = self._trip(db, trip_id)
            draft = self._draft(db, trip_id, draft_id)
            if (body.base_version, body.event_revision, body.history_revision) != (
                draft.base_version, draft.event_revision, draft.history_revision
            ):
                reject("draft_token_conflict", "确认参数与草案绑定的版本/修订号不一致")
            if draft.status == "committed":
                version = self._version(db, trip_id, draft.committed_version)
                if version["confirmation"]["confirmed_by"] != body.confirmed_by:
                    reject("confirmation_conflict", "不能改写已保存的用户确认")
                return version
            self._check_tokens(trip, body)
            if draft.status != "pending":
                reject("draft_stale", "草案已失效，必须根据最新状态重新生成")
            if set(draft.handled_event_ids) != {e.event_id for e in self._events(db, trip_id) if e.active}:
                reject("event_set_conflict", "有效异常集合已改变")
            # Recompute inside the write transaction; never trust a cached result or caller's PASS.
            validation = self._evaluate(db, trip, draft.plan)
            self._require_pass(validation)
            next_version = trip["current_version"] + 1
            result = self._insert_version(
                db, trip_id, next_version, draft.plan,
                TripConstraints.model_validate_json(trip["constraints_json"]), validation,
                trip["event_revision"], trip["history_revision"], draft_id,
                {"request_id": body.request_id, "confirmed_by": body.confirmed_by,
                 "confirmed_at": datetime.now(timezone.utc)},
            )
            db.execute("UPDATE trips SET current_version=? WHERE trip_id=?", (next_version, trip_id))
            db.execute("UPDATE drafts SET status='committed', committed_version=? WHERE trip_id=? AND draft_id=?",
                       (next_version, trip_id, draft_id))
            self._stale_pending(db, trip_id)
            return result
        return self._mutate(trip_id, f"confirm_draft:{draft_id}", body, action)

    def lock_activities(self, trip_id, body: LockActivities):
        def action(db):
            trip = self._trip(db, trip_id)
            if (body.base_version, body.history_revision) != (trip["current_version"], trip["history_revision"]):
                reject("revision_conflict", "正式版本或历史修订号已变化")
            current = self._version(db, trip_id, trip["current_version"])
            if set(body.activity_ids) - {a["id"] for a in current["plan"]["activities"]}:
                reject("invalid_lock", "只能锁定当前正式行程中的活动", 422)
            previous = set(json.loads(trip["locked_ids_json"]))
            updated = previous | set(body.activity_ids)
            if updated != previous:
                db.execute("UPDATE trips SET locked_ids_json=?, history_revision=history_revision+1 WHERE trip_id=?",
                           (encode(sorted(updated)), trip_id))
                self._stale_pending(db, trip_id)
            return self._view(db, trip_id)
        return self._mutate(trip_id, "lock_activities", body, action)
