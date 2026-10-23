"""Order lifecycle management (Slice 7): event identity, idempotent processing, submission
uncertainty, halts. Broker-neutral; deterministic; no I/O, wall clock or randomness."""

from risk_execution.order_lifecycle.checkpoint import CheckpointError, CheckpointStore
from risk_execution.order_lifecycle.events import BrokerEvent, EventKind, event_from_fill_report
from risk_execution.order_lifecycle.manager import (
    ApprovalError,
    EventResult,
    EventStatus,
    ExecutionHalted,
    HaltRecord,
    OrderLifecycleManager,
    OrderRecord,
    SubmissionStatus,
    SubmitOutcome,
    SubmitResult,
    UnresolvedSubmission,
)

__all__ = [
    "ApprovalError", "BrokerEvent", "CheckpointError", "CheckpointStore", "EventKind", "EventResult", "EventStatus", "ExecutionHalted",
    "HaltRecord", "OrderLifecycleManager", "OrderRecord", "SubmissionStatus", "SubmitOutcome",
    "SubmitResult", "UnresolvedSubmission", "event_from_fill_report",
]
