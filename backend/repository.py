"""CRUD helpers for the persistence layer.

These wrap SQLAlchemy primitives so callers (main.py + ws handlers)
do not interact with the session API directly. Each helper is a single
unit of work; callers open/close a session at message boundaries.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import SavedConstraints, SavedTrip, UserProfile


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
