"""TravelPlanState — shared state schema for the F1 travel planning graph.

Reducer note: only `messages` has multiple parallel writers (every agent
appends its own status lines to it), so it's the only field that needs
`Annotated[list, operator.add]`. All other list fields are written by
exactly one node, so LangGraph's default replace-semantics is correct
for them — and necessary, because during the budget retry loop the same
node runs again and should replace its previous output, not append.
"""

from __future__ import annotations
import operator
from typing import Annotated, Any
from typing_extensions import NotRequired, TypedDict


class TicketOption(TypedDict):
    name: str           # e.g. "Tribuna 25"
    price: float        # e.g. 380.0
    currency: str       # e.g. "EUR"
    section: str        # e.g. "T2 braking zone"
    tag: str            # e.g. "PICK"
    link: str           # booking URL
    provider: NotRequired[str]
    link_type: NotRequired[str]
    booking_confidence: NotRequired[str]
    _rationale: NotRequired[dict[str, Any]]


class TransportLeg(TypedDict):
    tag: str            # "OUT" | "RET" | "LOCAL"
    summary: str        # e.g. "NYC → Milan MXP"
    detail: str         # e.g. "Direct · 8h20m · Sep 4"
    price: float
    currency: str
    link: str
    provider: NotRequired[str]
    link_type: NotRequired[str]
    booking_confidence: NotRequired[str]
    _rationale: NotRequired[dict[str, Any]]


class HotelOption(TypedDict):
    name: str
    price_per_night: float
    total_price: float
    currency: str
    nights: int
    distance: str       # e.g. "2km to circuit"
    rating: str         # e.g. "8.4★"
    tag: str            # e.g. "NEAR"
    link: str
    provider: NotRequired[str]
    link_type: NotRequired[str]
    booking_confidence: NotRequired[str]
    _rationale: NotRequired[dict[str, Any]]


class BudgetSummary(TypedDict):
    items: list[dict[str, Any]]   # [{name, amount, currency}]
    total: float
    budget: float
    currency: str
    within_budget: bool
    savings_tip: str
    basis: NotRequired[str]                    # baseline | selected
    quote_complete: NotRequired[bool]
    missing_price_categories: NotRequired[list[str]]
    selected_indices: NotRequired[dict[str, list[int]]]


class TravelPlanState(TypedDict):
    # ── User input (set by parse_input) ──
    gp_name: str
    gp_city: str
    gp_date: str
    origin: str
    budget: float
    currency: str            # "EUR" | "USD" | "CNY" — budget/display currency
    stand_pref: str          # "any" | "ga" | "mid" | "vip"
    extra_days: int          # legacy; honored only when depart_date/return_date are empty
    depart_date: str         # ISO YYYY-MM-DD; when set with return_date, takes priority over extra_days
    return_date: str         # ISO YYYY-MM-DD
    stops: str               # multi-stop route description
    special_requests: str
    active_constraints: dict[str, Any]

    # ── Agent outputs ──
    # Single-writer fields: default replace-semantics. This is important
    # for the retry loop — we want a re-run of hotel/itinerary/tour to
    # replace the previous attempt, not accumulate on top of it.
    tickets: list[TicketOption]
    transport: list[TransportLeg]
    hotel: list[HotelOption]
    itinerary: list[str]          # day-by-day lines
    tour: list[str]                # recommendation lines
    budget_summary: BudgetSummary | None

    # ── Control flow ──
    budget_ok: bool
    retry_count: int

    # ── Streaming messages for frontend ──
    messages: Annotated[list[dict], operator.add]      # {agent, text, type}
