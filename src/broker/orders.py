import csv
import os
from datetime import datetime
from typing import Literal

import pandas as pd
from ib_insync import Stock, MarketOrder, LimitOrder

from .ibkr import IBKRConnection

TRADES_LOG = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "trades.csv")
LOG_HEADER = ["timestamp", "ticker", "action", "qty", "order_type", "limit_price", "status"]


def _init_log() -> None:
    path = os.path.abspath(TRADES_LOG)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(LOG_HEADER)


def _log_trade(ticker: str, action: str, qty: float, order_type: str,
               limit_price: float | None, status: str) -> None:
    _init_log()
    with open(os.path.abspath(TRADES_LOG), "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(), ticker, action, qty,
            order_type, limit_price or "", status,
        ])


def place_market_order(
    conn: IBKRConnection,
    ticker: str,
    qty: float,
    action: Literal["BUY", "SELL"],
) -> int:
    contract = Stock(ticker, "SMART", "USD")
    conn.ib.qualifyContracts(contract)
    order = MarketOrder(action, abs(qty))
    trade = conn.ib.placeOrder(contract, order)
    conn.ib.sleep(1)
    status = trade.orderStatus.status
    _log_trade(ticker, action, qty, "MKT", None, status)
    print(f"  {action:4} {abs(qty):6.0f} {ticker:6}  [MKT]  -> {status}")
    return trade.order.orderId


def place_limit_order(
    conn: IBKRConnection,
    ticker: str,
    qty: float,
    action: Literal["BUY", "SELL"],
    limit_price: float,
) -> int:
    contract = Stock(ticker, "SMART", "USD")
    conn.ib.qualifyContracts(contract)
    order = LimitOrder(action, abs(qty), limit_price)
    trade = conn.ib.placeOrder(contract, order)
    conn.ib.sleep(1)
    status = trade.orderStatus.status
    _log_trade(ticker, action, qty, "LMT", limit_price, status)
    print(f"  {action:4} {abs(qty):6.0f} {ticker:6}  [LMT @ {limit_price:.2f}]  -> {status}")
    return trade.order.orderId


def execute_rebalance(
    conn: IBKRConnection,
    target_weights: pd.Series,
    capital: float,
    dry_run: bool = False,
) -> list[dict]:
    """
    Computa las órdenes necesarias para alcanzar target_weights y las ejecuta.

    target_weights: Series con índice = tickers, valores = pesos objetivo [-1, 1]
    capital: valor total del portafolio en USD
    dry_run: si True, solo muestra las órdenes sin ejecutarlas
    """
    positions_df = conn.get_positions() if not dry_run else pd.DataFrame(
        columns=["ticker", "qty", "market_price", "market_value"]
    )

    current_values: dict[str, float] = {}
    prices: dict[str, float] = {}

    if not positions_df.empty:
        for _, row in positions_df.iterrows():
            current_values[row["ticker"]] = row["market_value"]
            prices[row["ticker"]] = row["market_price"]

    orders = []
    print(f"\n{'-'*55}")
    print(f"  Rebalanceo {'(DRY RUN) ' if dry_run else ''}— Capital: ${capital:,.0f}")
    print(f"{'-'*55}")

    for ticker, w_target in target_weights.items():
        target_value = w_target * capital
        current_value = current_values.get(ticker, 0.0)
        delta_value = target_value - current_value

        # Obtener precio si no lo tenemos
        if ticker not in prices:
            try:
                prices[ticker] = conn.get_market_price(ticker) if not dry_run else 100.0
            except Exception:
                prices[ticker] = 100.0

        price = prices[ticker]
        if price == 0:
            continue

        qty = delta_value / price
        if abs(qty) < 1:
            continue

        action: Literal["BUY", "SELL"] = "BUY" if qty > 0 else "SELL"
        order = {"ticker": ticker, "action": action, "qty": round(abs(qty)), "price": price}
        orders.append(order)

        if dry_run:
            print(f"  {action:4} {round(abs(qty)):6} {ticker:6}  @ ~{price:.2f}  "
                  f"(D${delta_value:+,.0f})")
        else:
            place_market_order(conn, ticker, round(abs(qty)), action)

    print(f"{'-'*55}")
    print(f"  Total órdenes: {len(orders)}")
    return orders
