"""
Pure Python paper broker — full Kelly sizing .
Matches buy_all/sell_all from strategy_helpers.py.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PaperBroker:
    """
    Paper trading broker with full Kelly position sizing.
    No commission (matching _execute).

    Attributes:
        starting_cash: Initial USD capital.
        cash:          Available USD.
        position_size: Current oz held. 0 if flat.
        peak_price:    Highest price since entry (trailing stop).
        in_position:   Whether a position is held.
        last_trade_bar: Bar index of last trade.
        num_trades:    Total completed round-trips.
        exit_reason_trailing: True if last exit was trailing stop.
    """

    starting_cash: float = 10_000.0

    # Mutable state
    cash: float = field(default=10_000.0)
    position_size: float = field(default=0.0)
    peak_price: float = field(default=0.0)
    in_position: bool = field(default=False)
    last_trade_bar: int = field(default=0)
    num_trades: int = field(default=0)
    exit_reason_trailing: bool = field(default=False)

    # ── Full Kelly Buy ─────────────────────────────────────────────────────

    def buy(self, price: float) -> dict:
        """Full Kelly: invest all cash at price. No commission."""
        if self.in_position:
            return {"success": False, "reason": "already_in_position"}
        if self.cash <= 0 or price <= 0:
            return {"success": False, "reason": "insufficient_cash"}

        qty = self.cash / price
        qty = max(qty, 0.0)

        self.cash = 0.0
        self.position_size = qty
        self.peak_price = price
        self.in_position = True
        self.exit_reason_trailing = False

        return {
            "success": True,
            "side": "BUY",
            "price": price,
            "quantity": qty,
            "cash_after": self.cash,
        }

    # ── Full Kelly Sell ─────────────────────────────────────────────────────

    def sell(self, price: float, exit_reason: str = "manual") -> dict:
        """Full Kelly: close entire position at price. No commission."""
        if not self.in_position:
            return {"success": False, "reason": "no_position"}

        qty = self.position_size
        proceeds = qty * price

        pnl = proceeds - (self.peak_price * qty)  # relative to entry (peak used as entry)

        self.cash += proceeds
        self.num_trades += 1
        self.exit_reason_trailing = (exit_reason == "trailing_stop")

        self.position_size = 0.0
        self.peak_price = 0.0
        self.in_position = False

        return {
            "success": True,
            "side": "SELL",
            "price": price,
            "quantity": qty,
            "pnl": pnl,
            "exit_reason": exit_reason,
            "cash_after": self.cash,
        }

    # ── Portfolio helpers ───────────────────────────────────────────────────

    def get_portfolio_value(self, current_price: float) -> float:
        if self.in_position:
            return self.cash + (self.position_size * current_price)
        return self.cash

    def get_unrealized_pnl(self, current_price: float) -> float:
        if not self.in_position:
            return 0.0
        return (current_price - self.peak_price) * self.position_size

    def get_realized_pnl(self) -> float:
        return self.cash - self.starting_cash

    # ── Trailing stop level ────────────────────────────────────────────────

    def get_trailing_stop_level(
        self,
        atr: float,
        price: float,
        roc_fast: float,
        roc_slow: float,
        base_mult: float = 2.5,
        tighten_mult: float = 1.25,
        mom_strong_thresh: float = 2.5,
    ) -> float:
        """Compute trailing stop price level."""
        if atr <= 0 or price <= 0:
            return price * 0.95

        stop_distance_pct = (base_mult * atr) / price
        mom_strength = roc_fast - roc_slow
        if mom_strength > mom_strong_thresh:
            tighten = (tighten_mult * atr) / price
            stop_distance_pct = max(stop_distance_pct - tighten, 0.01)

        return price * (1.0 - stop_distance_pct)

    # ── Bar tracking ───────────────────────────────────────────────────────

    def bars_since_trade(self, current_bar: int) -> int:
        return current_bar - self.last_trade_bar

    def mark_trade_bar(self, current_bar: int):
        self.last_trade_bar = current_bar
