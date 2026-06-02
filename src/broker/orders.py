"""
Ejecución y registro de órdenes contra IBKR.

Registra en dos niveles (consigna: "registrar y monitorear las operaciones"):
  - logs/trades.csv      : una fila por orden (con precio de fill, motivo, id de
                           rebalanceo al que pertenece).
  - logs/rebalances.csv  : una fila por evento de rebalanceo / corte (cuántas
                           órdenes, nocional bruto operado, parámetros, estado).

Seguridad: execute_rebalance() se niega a operar si la estrategia está HALTED
(ver src/broker/state.py). close_all_positions() es el "kill switch": cierra
todas las posiciones a mercado.
"""
import csv
import os
from datetime import datetime
from typing import Literal

import pandas as pd
from ib_insync import Stock, MarketOrder, LimitOrder

from .ibkr import IBKRConnection
from . import state

_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))
TRADES_LOG = os.path.join(_LOG_DIR, "trades.csv")
REBALANCES_LOG = os.path.join(_LOG_DIR, "rebalances.csv")

TRADE_HEADER = ["timestamp", "rebalance_id", "ticker", "action", "qty",
                "order_type", "limit_price", "fill_price", "status", "reason"]
REBAL_HEADER = ["timestamp", "rebalance_id", "trigger", "signal_mode", "lookback",
                "target_vol", "capital", "n_orders", "gross_notional", "status"]


def _yf_price(ticker: str) -> float:
    import yfinance as yf
    info = yf.Ticker(ticker).fast_info
    price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
    return float(price) if price else 100.0


def _yf_prices_batch(tickers: list[str]) -> dict[str, float]:
    """Precios de cierre recientes de TODOS los tickers en UNA sola descarga.

    Acelera el dry-run del dashboard (evita ~N llamadas sueltas a yfinance).
    """
    import yfinance as yf
    tickers = list(tickers)
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="5d", auto_adjust=True, progress=False)
        close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
        if isinstance(close, pd.Series):
            close = close.to_frame(tickers[0])
        last = close.ffill().iloc[-1]
        return {t: float(last[t]) for t in tickers
                if t in last.index and pd.notna(last[t])}
    except Exception:
        return {}


def _new_rebalance_id(tag: str = "RB") -> str:
    return f"{tag}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _init_log(path: str, header: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(header)


def _log_trade(rebalance_id: str, ticker: str, action: str, qty: float, order_type: str,
               limit_price: float | None, fill_price: float | str, status: str,
               reason: str) -> None:
    _init_log(TRADES_LOG, TRADE_HEADER)
    with open(TRADES_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(timespec="seconds"), rebalance_id, ticker, action,
            qty, order_type, limit_price if limit_price is not None else "",
            fill_price, status, reason,
        ])


def _log_rebalance(rebalance_id: str, trigger: str, n_orders: int, gross_notional: float,
                   capital: float, status: str, params: dict | None = None) -> None:
    _init_log(REBALANCES_LOG, REBAL_HEADER)
    params = params or {}
    with open(REBALANCES_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(timespec="seconds"), rebalance_id, trigger,
            params.get("signal_mode", ""), params.get("lookback", ""),
            params.get("target_vol", ""), round(capital, 2), n_orders,
            round(gross_notional, 2), status,
        ])


def _await_fill(conn: IBKRConnection, trade, timeout_s: float = 15.0) -> None:
    """Espera (acotado) a que la orden se complete/cancele para registrar el fill.

    En horario regular el fill es casi inmediato (corta enseguida); en horario
    extendido puede demorar varios segundos, por eso el margen amplio."""
    waited = 0.0
    done = ("Filled", "Cancelled", "ApiCancelled", "Inactive")
    while waited < timeout_s and trade.orderStatus.status not in done:
        conn.ib.sleep(0.5)
        waited += 0.5


def place_market_order(
    conn: IBKRConnection,
    ticker: str,
    qty: float,
    action: Literal["BUY", "SELL"],
    rebalance_id: str = "",
    reason: str = "rebalance",
    contract=None,
) -> dict:
    # Si nos pasan el contrato EXACTO (p.ej. al cerrar una posición: warrant, opción,
    # un conId puntual) lo usamos tal cual pero ruteando por SMART. Si no, asumimos
    # que es un ETF/acción del universo y lo construimos como Stock SMART/USD.
    if contract is None:
        contract = Stock(ticker, "SMART", "USD")
        conn.ib.qualifyContracts(contract)
    else:
        contract.exchange = "SMART"  # rutear smart aunque el contrato venga con primary exchange
    order = MarketOrder(action, abs(qty))
    # TIF explícito DAY: sin esto, el preset de orden de TWS fuerza el TIF y dispara
    # el error 10349 (cancela y reenvía la orden) → el status queda mal registrado.
    order.tif = "DAY"
    trade = conn.ib.placeOrder(contract, order)
    conn.ib.sleep(1)
    _await_fill(conn, trade)
    status = trade.orderStatus.status
    fill_price = trade.orderStatus.avgFillPrice or ""
    _log_trade(rebalance_id, ticker, action, qty, "MKT", None, fill_price, status, reason)
    print(f"  {action:4} {abs(qty):>6g} {ticker:6}  [MKT]  -> {status}"
          f"{f' @ {fill_price:.2f}' if fill_price else ''}")
    return {"order_id": trade.order.orderId, "ticker": ticker, "action": action,
            "qty": abs(qty), "fill_price": fill_price, "status": status}


def place_limit_order(
    conn: IBKRConnection,
    ticker: str,
    qty: float,
    action: Literal["BUY", "SELL"],
    limit_price: float,
    rebalance_id: str = "",
    reason: str = "rebalance",
) -> dict:
    contract = Stock(ticker, "SMART", "USD")
    conn.ib.qualifyContracts(contract)
    order = LimitOrder(action, abs(qty), limit_price)
    order.tif = "DAY"  # evita el error 10349 del preset de TWS (ver place_market_order)
    trade = conn.ib.placeOrder(contract, order)
    conn.ib.sleep(1)
    status = trade.orderStatus.status
    _log_trade(rebalance_id, ticker, action, qty, "LMT", limit_price,
               trade.orderStatus.avgFillPrice or "", status, reason)
    print(f"  {action:4} {abs(qty):6.0f} {ticker:6}  [LMT @ {limit_price:.2f}]  -> {status}")
    return {"order_id": trade.order.orderId, "ticker": ticker, "action": action,
            "qty": abs(qty), "status": status}


def execute_rebalance(
    conn: IBKRConnection,
    target_weights: pd.Series,
    capital: float,
    dry_run: bool = False,
    trigger: str = "manual",
    params: dict | None = None,
) -> list[dict]:
    """
    Computa las órdenes necesarias para alcanzar target_weights y las ejecuta.

    target_weights: Series índice = tickers, valores = pesos objetivo [-1, 1]
    capital: valor total del portafolio en USD
    dry_run: si True, solo computa las órdenes sin ejecutarlas ni registrarlas
    trigger: origen del rebalanceo (ej. "manual", "dashboard") — para el log
    """
    if not dry_run and state.is_halted():
        raise RuntimeError(
            "Estrategia CORTADA (halted). Reanudá la estrategia antes de operar.")

    rebalance_id = _new_rebalance_id("RB")
    positions_df = conn.get_positions() if (not dry_run and conn is not None) else pd.DataFrame(
        columns=["ticker", "qty", "market_price", "market_value"]
    )

    current_values: dict[str, float] = {}
    prices: dict[str, float] = {}
    if not positions_df.empty:
        for _, row in positions_df.iterrows():
            current_values[row["ticker"]] = row["market_value"]
            prices[row["ticker"]] = row["market_price"]

    # Precargar TODOS los precios en una sola descarga de yfinance (dry-run Y vivo).
    # Sirve solo para DIMENSIONAR las órdenes (el fill real es a mercado). En vivo
    # esto evita pedir a IBKR ticker por ticker —lento y, sin suscripción de datos,
    # devuelve NaN—: pasa de ~minutos a ~segundos.
    prices.update({t: p for t, p in _yf_prices_batch(list(target_weights.index)).items()
                   if t not in prices})

    orders = []
    print(f"\n{'-'*55}")
    print(f"  Rebalanceo {rebalance_id} {'(DRY RUN) ' if dry_run else ''}— Capital: ${capital:,.0f}")
    print(f"{'-'*55}")

    for ticker, w_target in target_weights.items():
        target_value = w_target * capital
        current_value = current_values.get(ticker, 0.0)
        delta_value = target_value - current_value

        price = prices.get(ticker)
        # Precio inválido (faltante / 0 / NaN): IBKR puede no devolver precio si la
        # cuenta no tiene suscripción de datos (error 10089). Caemos a yfinance para
        # dimensionar la orden en vez de crashear (el fill real es a mercado igual).
        if price is None or price != price or price <= 0:
            try:
                price = conn.get_market_price(ticker) if not dry_run else _yf_price(ticker)
            except Exception:
                price = 0.0
            if price is None or price != price or price <= 0:
                try:
                    price = _yf_price(ticker)
                except Exception:
                    price = 0.0
            prices[ticker] = price

        if not price or price != price or price <= 0:
            continue

        qty = delta_value / price
        if abs(qty) < 1:
            continue

        action: Literal["BUY", "SELL"] = "BUY" if qty > 0 else "SELL"
        order = {"ticker": ticker, "action": action, "qty": round(abs(qty)),
                 "price": round(price, 2), "delta_usd": round(delta_value)}
        orders.append(order)

        if dry_run:
            print(f"  {action:4} {round(abs(qty)):6} {ticker:6}  @ ~{price:.2f}  "
                  f"(D${delta_value:+,.0f})")
        else:
            place_market_order(conn, ticker, round(abs(qty)), action,
                               rebalance_id=rebalance_id, reason="rebalance")

    gross_notional = sum(abs(o["qty"] * o["price"]) for o in orders)
    print(f"{'-'*55}")
    print(f"  Total órdenes: {len(orders)}  ·  Nocional bruto: ${gross_notional:,.0f}")

    if not dry_run:
        _log_rebalance(rebalance_id, trigger, len(orders), gross_notional, capital,
                       status="executed", params=params)
        # Marca el estado: el guard mensual y el catch-up al reconectar leen esto.
        state.record_rebalance(rebalance_id)
    return orders


def close_all_positions(
    conn: IBKRConnection,
    dry_run: bool = False,
    reason: str = "kill switch",
) -> list[dict]:
    """
    KILL SWITCH: cierra TODAS las posiciones a mercado y cancela órdenes abiertas.

    No marca el halt flag por sí solo (eso lo decide quien llama, ej. el botón del
    dashboard llama a state.halt() además de esto). Devuelve la lista de órdenes
    de cierre (en dry_run solo las computa).
    """
    rebalance_id = _new_rebalance_id("KILL")
    # Posiciones con su CONTRATO EXACTO (no agregadas por símbolo): así cerramos el
    # instrumento correcto aunque un símbolo tenga acción + warrants (bug viejo: se
    # reconstruía un Stock y se operaba el instrumento equivocado).
    raw = conn.get_raw_positions() if conn is not None else []

    closeable, fractional = [], []
    for p in raw:
        qty = p["qty"]
        action: Literal["BUY", "SELL"] = "SELL" if qty > 0 else "BUY"
        item = {"ticker": p["symbol"], "secType": p["secType"], "action": action,
                "qty": abs(qty), "contract": p["contract"]}
        # Fraccionario: la API de IBKR lo rechaza (error 10243) — solo TWS desktop.
        if abs(abs(qty) - round(abs(qty))) > 1e-9:
            fractional.append(item)
        else:
            closeable.append(item)

    print(f"\n{'='*55}")
    print(f"  KILL SWITCH {rebalance_id} {'(DRY RUN) ' if dry_run else ''}— "
          f"{len(closeable)} cerrables · {len(fractional)} fraccionarias (manual)")
    print(f"{'='*55}")

    for o in fractional:
        print(f"  [!] {o['ticker']} [{o['secType']}]: posición fraccionaria ({o['qty']}) — "
              f"la API de IBKR no permite cerrarla. Cerrala en TWS desktop.")

    if not dry_run and conn is not None:
        # Cancelar pendientes primero — solo si las hay (evita el ruido de error 161
        # "no cancelable" cuando todas las órdenes ya se completaron).
        if not conn.get_open_orders().empty:
            conn.cancel_all_orders()
        for o in closeable:
            place_market_order(conn, o["ticker"], o["qty"], o["action"],
                               rebalance_id=rebalance_id, reason=reason,
                               contract=o["contract"])
        _log_rebalance(rebalance_id, trigger="KILL", n_orders=len(closeable),
                       gross_notional=0.0, capital=0.0, status="executed")
    else:
        for o in closeable:
            print(f"  {o['action']:4} {o['qty']:>6g} {o['ticker']:6} [{o['secType']}]  [cerrar]")

    print(f"{'='*55}")
    # Devolvemos sin el objeto contract (no serializable) para el dashboard/logs.
    return [{k: v for k, v in o.items() if k != "contract"} for o in (closeable + fractional)]
