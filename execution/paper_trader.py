"""
Paper trading simulator.

Simulates trade fills at market prices and tracks P&L without real money.
Stores state in data/paper_portfolio.json so paper positions survive restarts.

Usage::

    from execution.paper_trader import PaperTrader

    pt = PaperTrader()
    pt.place_order("BUY", "AAPL", 10, fill_price=150.00)
    print(pt.summary())
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PAPER_STATE_PATH = Path("data/paper_portfolio.json")
PAPER_HISTORY_PATH = Path("data/paper_trade_history.json")


@dataclass
class PaperPosition:
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100


@dataclass
class PaperTrade:
    timestamp: str
    symbol: str
    side: str  # BUY or SELL
    quantity: int
    price: float
    notional: float
    reason: str = ""


class PaperTrader:
    """
    Simulates a brokerage account with fill simulation and P&L tracking.

    All methods are synchronous and read/write JSON state to disk.
    """

    def __init__(self, initial_cash: float = 100_000.0):
        self.state_path = PAPER_STATE_PATH
        self.history_path = PAPER_HISTORY_PATH
        self.initial_cash = initial_cash
        self._load_state()

    def _load_state(self) -> None:
        if self.state_path.exists():
            raw = json.loads(self.state_path.read_text())
            self.cash = raw.get("cash", self.initial_cash)
            self.positions: dict[str, PaperPosition] = {}
            for p in raw.get("positions", []):
                pos = PaperPosition(
                    symbol=p["symbol"],
                    quantity=p["quantity"],
                    avg_cost=p["avg_cost"],
                    current_price=p.get("current_price", 0.0),
                )
                self.positions[pos.symbol] = pos
        else:
            self.cash = self.initial_cash
            self.positions = {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "cash": round(self.cash, 2),
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": round(p.avg_cost, 4),
                    "current_price": round(p.current_price, 4),
                }
                for p in self.positions.values()
            ],
        }, indent=2))

    def _record_trade(self, trade: PaperTrade) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        trades = []
        if self.history_path.exists():
            trades = json.loads(self.history_path.read_text())
        trades.append({
            "timestamp": trade.timestamp,
            "symbol": trade.symbol,
            "side": trade.side,
            "quantity": trade.quantity,
            "price": round(trade.price, 4),
            "notional": round(trade.notional, 2),
            "reason": trade.reason,
        })
        # Keep last 5000 trades
        if len(trades) > 5000:
            trades = trades[-5000:]
        self.history_path.write_text(json.dumps(trades, indent=2))

    def place_order(
        self,
        side: str,
        symbol: str,
        quantity: int,
        fill_price: float,
        reason: str = "",
    ) -> dict:
        """
        Simulate a trade fill.

        Parameters
        ----------
        side : "BUY" or "SELL"
        symbol : str
        quantity : int
        fill_price : float — the market price at fill time
        reason : str — optional description (e.g., "MACD crossover signal")

        Returns
        -------
        dict with status, fill_price, notional, new_cash, new_position
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            return {"error": f"Invalid side: {side}"}
        if quantity <= 0:
            return {"error": "Quantity must be positive"}

        notional = quantity * fill_price

        if side == "BUY":
            if notional > self.cash:
                # Scale down to available cash
                quantity = max(int(self.cash // fill_price), 0)
                if quantity == 0:
                    return {"error": "Insufficient funds", "notional": notional, "cash": self.cash}
                notional = quantity * fill_price

            self.cash -= notional
            if symbol in self.positions:
                pos = self.positions[symbol]
                total_qty = pos.quantity + quantity
                total_cost = pos.cost_basis + notional
                pos.quantity = total_qty
                pos.avg_cost = total_cost / total_qty if total_qty > 0 else 0
            else:
                self.positions[symbol] = PaperPosition(
                    symbol=symbol, quantity=quantity, avg_cost=fill_price,
                    current_price=fill_price,
                )

        else:  # SELL
            if symbol not in self.positions:
                return {"error": f"No position in {symbol}"}
            pos = self.positions[symbol]
            if quantity > pos.quantity:
                quantity = pos.quantity  # sell all we have
                notional = quantity * fill_price

            self.cash += notional
            pos.quantity -= quantity
            if pos.quantity <= 0:
                del self.positions[symbol]

        trade = PaperTrade(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=symbol, side=side, quantity=quantity,
            price=fill_price, notional=notional, reason=reason,
        )
        self._record_trade(trade)
        self._save_state()

        return {
            "status": "filled",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "fill_price": fill_price,
            "notional": round(notional, 2),
            "cash": round(self.cash, 2),
            "position": self.positions.get(symbol),
        }

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update current market prices for all tracked positions."""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = price

    def total_equity(self) -> float:
        """Cash + market value of all positions."""
        mv = sum(p.market_value for p in self.positions.values())
        return self.cash + mv

    def total_pnl(self) -> float:
        """Total P&L since inception."""
        return self.total_equity() - self.initial_cash

    def total_pnl_pct(self) -> float:
        """Total P&L as percentage of initial capital."""
        if self.initial_cash == 0:
            return 0.0
        return (self.total_pnl() / self.initial_cash) * 100

    def summary(self) -> dict:
        """Return a dict suitable for display in the UI."""
        positions_list = []
        for p in self.positions.values():
            positions_list.append({
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_cost": round(p.avg_cost, 4),
                "current_price": round(p.current_price, 4),
                "market_value": round(p.market_value, 2),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 2),
            })

        return {
            "cash": round(self.cash, 2),
            "equity": round(self.total_equity(), 2),
            "total_pnl": round(self.total_pnl(), 2),
            "total_pnl_pct": round(self.total_pnl_pct(), 2),
            "positions": positions_list,
            "position_count": len(positions_list),
        }

    def get_trade_history(self, limit: int = 50) -> list[dict]:
        """Return recent trades."""
        if not self.history_path.exists():
            return []
        trades = json.loads(self.history_path.read_text())
        return trades[-limit:]

    def reset(self) -> None:
        """Reset paper portfolio to initial state."""
        self.cash = self.initial_cash
        self.positions = {}
        self._save_state()
        if self.history_path.exists():
            self.history_path.write_text("[]")
