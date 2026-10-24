"""Recovery sweep: book lifecycle-recorded fills into the portfolio exactly once (Slice 7 final closure, ADR-13).

Lives in the `simulation` leaf package because it must see both the lifecycle manager and the research portfolio,
which are not allowed to import each other. Order of operations per pending fill: (1) `ResearchPortfolio.apply_fill`
(idempotent by fill_id; durable if the portfolio has a checkpoint), (2) `mark_portfolio_applied` on the manager.
A crash between (1) and (2) is safe: the next sweep sees ALREADY_APPLIED and only records the confirmation.
"""

from __future__ import annotations

from risk_execution.order_lifecycle import OrderLifecycleManager
from research.harness.failures import FailureCategory, ResearchRunFailure
from research.harness.portfolio import FillApplication, ResearchPortfolio


def apply_pending_fills(mgr: OrderLifecycleManager, portfolio: ResearchPortfolio) -> list[FillApplication]:
    results: list[FillApplication] = []
    for key, f in mgr.fills_pending_portfolio_application():
        rec = mgr.record(key)
        if rec is None or f.charges_total is None:  # cash effect unverifiable: never guess a cost of zero
            raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                     f"fill {f.fill_id} cannot be settled: charges unknown or order record missing",
                                     fill_id=f.fill_id)
        app = portfolio.apply_fill(f.fill_id, rec.request.instrument_id, f.side, f.quantity, f.price, f.charges_total,
                                   order_id=f.order_id, source=f.source)
        mgr.mark_portfolio_applied(f.fill_id)
        results.append(app)
    return results
