# ruff: noqa: UP042
# Keep existing Enum string/serialization semantics across slices.
"""Enumerations shared by the domain models (Stage 3 §2, §4, §9)."""

from __future__ import annotations

from enum import Enum


class Action(str, Enum):
    """CandidateTrade.action — HOLD is first-class, never inferred (TR-4)."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class UncertaintyBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Segment(str, Enum):
    """Instrument.segment — equity only in v1, per TR-1 / Stage 3 §2 note."""

    EQUITY = "EQUITY"


class PositionSide(str, Enum):
    """Position.side — long only assumed in v1 unless later specified (Stage 3 §2)."""

    LONG = "LONG"


class RiskVerdict(str, Enum):
    """RiskDecision.final_verdict (Stage 3 §7)."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RESIZE = "RESIZE"


class PortfolioStateSource(str, Enum):
    """PortfolioState.source — distinguishes system-belief from broker-confirmed (Stage 3 §2)."""

    SYSTEM_BELIEF = "SYSTEM_BELIEF"
    BROKER_CONFIRMED = "BROKER_CONFIRMED"


class FillType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class OrderState(str, Enum):
    """The order lifecycle state machine (Stage 3 §9)."""

    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class TerminalState(str, Enum):
    """DecisionRecord.terminal_state (Stage 3 §4)."""

    NO_CANDIDATE = "NO_CANDIDATE"
    REJECTED_AT_RISK = "REJECTED_AT_RISK"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED_BY_BROKER = "REJECTED_BY_BROKER"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    # Slice 8 (ADR-14, additive): explicit, distinguishable no-order outcomes. The original eight members and
    # their meanings are unchanged; HOLD (a candidate whose action is HOLD) is NOT NO_CANDIDATE (no candidate).
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"  # candidate existed but produced no order (e.g. SELL with nothing held, sizing no-trade)
    SKIPPED_PENDING_ORDER = "SKIPPED_PENDING_ORDER"  # an earlier order for the instrument is still unfilled
    REJECTED_INVALID_CANDIDATE = "REJECTED_INVALID_CANDIDATE"  # candidate failed validation


class PromotionDecision(str, Enum):
    """PromotionCandidate.decision (Stage 3 §2, §14) — no third 'pending' value

    is modeled here on purpose: a PromotionCandidate that has not yet been
    decided simply has `decision=None` (see promotion.py), so "not yet
    reviewed" and "reviewed and rejected" can never be confused.
    """

    APPROVE = "APPROVE"
    REJECT = "REJECT"
