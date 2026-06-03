"""CRUD helpers for the persistence layer.

These wrap SQLAlchemy primitives so callers (main.py + ws handlers)
do not interact with the session API directly. Each helper is a single
unit of work; callers open/close a session at message boundaries.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import SavedConstraints, SavedTrip, UserProfile


class SavedTripQuotaError(RuntimeError):
    """Raised when a user is at their saved-trips cap (BS-02)."""


def _saved_trips_per_user_max() -> int:
    """Per-user saved-trips cap. 0 (or negative) disables the cap.

    Env-configurable per the project's "new tunable limits" rule; defaults
    to 100. Bounds storage cost/abuse since save_trip is an unconditional
    INSERT with no upsert/replace.
    """
    try:
        return max(int(os.environ.get("SAVED_TRIPS_PER_USER_MAX", "100")), 0)
    except (TypeError, ValueError):
        return 100


def count_trips(db: Session, *, user_id: uuid.UUID) -> int:
    """Total saved trips owned by a user (not capped by the list READ limit)."""
    return int(
        db.scalar(
            select(func.count()).select_from(SavedTrip).where(SavedTrip.user_id == user_id)
        )
        or 0
    )


def upsert_user(
    db: Session,
    *,
    clerk_user_id: str,
    email: str | None,
    display_name: str | None,
) -> UserProfile:
    row = db.scalar(select(UserProfile).where(UserProfile.clerk_user_id == clerk_user_id))
    now = datetime.now(timezone.utc)
    if row is None:
        row = UserProfile(
            clerk_user_id=clerk_user_id,
            email=email,
            display_name=display_name,
            last_seen_at=now,
        )
        db.add(row)
    else:
        if email is not None:
            row.email = email
        if display_name is not None:
            row.display_name = display_name
        row.last_seen_at = now
    db.commit()
    db.refresh(row)
    return row


def save_trip(
    db: Session,
    *,
    user_id: uuid.UUID,
    gp_slug: str,
    depart_date: date | None,
    return_date: date | None,
    plan_snapshot: dict,
    budget_summary: dict | None,
    active_constraints: dict | None,
) -> SavedTrip:
    # Per-user storage quota (BS-02). Enforced before the INSERT so an
    # authenticated user/script cannot grow the table without bound.
    cap = _saved_trips_per_user_max()
    if cap > 0 and count_trips(db, user_id=user_id) >= cap:
        raise SavedTripQuotaError(
            f"saved-trips limit reached ({cap}). Delete an existing trip to save a new one."
        )
    trip = SavedTrip(
        user_id=user_id,
        gp_slug=gp_slug,
        depart_date=depart_date,
        return_date=return_date,
        plan_snapshot=plan_snapshot,
        budget_summary=budget_summary,
        active_constraints=active_constraints,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


def list_trips(db: Session, *, user_id: uuid.UUID, limit: int = 50) -> Sequence[SavedTrip]:
    return db.scalars(
        select(SavedTrip)
        .where(SavedTrip.user_id == user_id)
        .order_by(SavedTrip.created_at.desc())
        .limit(limit)
    ).all()


def get_trip(
    db: Session, *, trip_id: uuid.UUID, user_id: uuid.UUID
) -> SavedTrip | None:
    return db.scalar(
        select(SavedTrip).where(SavedTrip.id == trip_id, SavedTrip.user_id == user_id)
    )


def delete_trip(db: Session, *, trip_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    row = get_trip(db, trip_id=trip_id, user_id=user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def delete_user_by_clerk_id(db: Session, *, clerk_user_id: str) -> bool:
    """Delete a user_profiles row (and, via FK cascade, their saved_trips).

    Used by the Clerk user.deleted webhook (BS-03 / right-to-erasure). Returns
    True if a row was deleted, False if no such user existed (idempotent — a
    redelivered webhook for an already-gone user is a no-op success).
    """
    row = db.scalar(
        select(UserProfile).where(UserProfile.clerk_user_id == clerk_user_id)
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def upsert_constraints(
    db: Session, *, user_id: uuid.UUID, defaults: dict
) -> SavedConstraints:
    row = db.get(SavedConstraints, user_id)
    if row is None:
        row = SavedConstraints(user_id=user_id, defaults=defaults)
        db.add(row)
    else:
        row.defaults = defaults
    db.commit()
    db.refresh(row)
    return row


def get_constraints(db: Session, *, user_id: uuid.UUID) -> SavedConstraints | None:
    return db.get(SavedConstraints, user_id)
