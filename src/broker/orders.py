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
NAV_LOG = os.path.join(_LOG_DIR, "nav_history.csv")

TRADE_HEADER = ["timestamp", "rebalance_id", "ticker", "action", "qty",
                "order_type", "limit_price", "fill_price", "status", "reason"]
REBAL_HEADER = ["timestamp", "rebalance_id", "trigger", "kind", "signal_mode", "lookback",
                "target_vol", "capital", "n_orders", "gross_notional", "status"]

# Tipos de ejecución. Operar (mandar órdenes) y rebalancear (el evento mensual de
# calendario) son cosas distintas: TODA ejecución pasa por execute_rebalance, pero
# solo el rebalanceo mensual —y la allocación inicial, que también deja el mes al día—
# avanzan el reloj mensual (state.record_rebalance). Una realineación de drift, una
# liquidación o un test NO consumen el rebalanceo del mes.
KIND_ALLOCACION = "allocacion_inicial"   # primera compra al target (deja el mes al día)
KIND_MENSUAL    = "rebalanceo_mensual"   # el rebalanceo de calendario (mes nuevo)
KIND_REALINEACION = "realineacion"       # re-alinear drift ad-hoc (NO consume el mes)
KIND_LIQUIDACION  = "liquidacion"        # cerrar/vender posiciones (NO consume el mes)
KIND_TEST         = "test"               # operación de prueba (NO consume el mes)

# Tipos que CONSUMEN el slot del mes (avanzan el reloj para no operar de nuevo el mismo
# mes). Ojo: esto es distinto de "ser un rebalanceo". La allocación inicial marca el mes
# (no querés rebalancear el mismo mes que arrancaste) pero NO es un rebalanceo —en el
# registro/dashboard cuenta como OPERACIÓN. El único rebalanceo de verdad es el mensual.
_KINDS_QUE_MARCAN_MES = {KIND_ALLOCACION, KIND_MENSUAL}
NAV_HEADER = ["timestamp", "invested", "pnl", "ret_pct", "drift"]


_DATA_PARQUET = os.path.join(os.path.dirname(_LOG_DIR), "Data", "etf_prices.parquet")


def _parquet_last_prices(tickers: list[str]) -> dict[str, float]:
    """Últimos precios de cierre del parquet LOCAL (rápido, sin red, confiable).

    Fuente preferida para dimensionar órdenes: el parquet ya tiene los precios más
    recientes de todos los ETFs. Evita yfinance, que es lento y —con la fecha futura
    del entorno (2026)— falla con 'start date after end date'. El fill real es a
    mercado igual, así que alcanza con el último precio conocido."""
    try:
        df = pd.read_parquet(_DATA_PARQUET).ffill()
        last = df.iloc[-1]
        return {t: float(last[t]) for t in tickers
                if t in last.index and pd.notna(last[t]) and last[t] > 0}
    except Exception:
        return {}


def _yf_price(ticker: str) -> float:
    # Primero el parquet local (rápido/confiable); yfinance solo como último recurso.
    p = _parquet_last_prices([ticker]).get(ticker)
    if p:
        return p
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        return float(price) if price else 100.0
    except Exception:
        return 100.0


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


def clear_trade_logs() -> None:
    """Borra los logs de OPERACIONES (trades y rebalances) para arrancar de cero al
    'Detener y cerrar todo'. NO toca el historial de rendimiento (nav_history): ese
    es el track record de la estrategia y persiste entre sesiones."""
    for path in (TRADES_LOG, REBALANCES_LOG):
        if os.path.exists(path):
            os.remove(path)


def clear_nav_history() -> None:
    """Borra el historial de rendimiento (track record). Acción aparte y explícita:
    el kill switch NO lo borra; esto es para cuando el usuario quiere reiniciar el
    gráfico de cero a propósito."""
    if os.path.exists(NAV_LOG):
        os.remove(NAV_LOG)


def log_nav_snapshot(invested: float, pnl: float, drift: float = 0.0) -> None:
    """Registra una foto del rendimiento de la estrategia (para el gráfico en vivo).
    Se llama en cada refresh del monitoreo. Solo registra si hay capital invertido.
    `drift` = drift total (fracción a reasignar) en ese momento, para graficarlo.

    Robusto a cambios de esquema: lee lo existente, garantiza las columnas de
    NAV_HEADER (rellena las que falten en filas viejas) y reescribe. Así, agregar una
    columna nueva NO desalinea ni corrompe el historial previo."""
    if not invested or invested <= 0:
        return
    os.makedirs(os.path.dirname(NAV_LOG), exist_ok=True)
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "invested": round(invested, 2), "pnl": round(pnl, 2),
        "ret_pct": round(pnl / invested * 100, 4), "drift": round(drift, 4),
    }
    if os.path.exists(NAV_LOG) and os.path.getsize(NAV_LOG) > 0:
        try:
            df = pd.read_csv(NAV_LOG)
        except Exception:
            df = pd.DataFrame(columns=NAV_HEADER)
        for col in NAV_HEADER:                     # migrar esquema viejo si falta alguna
            if col not in df.columns:
                df[col] = 0.0
        df = pd.concat([df[NAV_HEADER], pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row], columns=NAV_HEADER)
    df.to_csv(NAV_LOG, index=False)


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
                   capital: float, status: str, kind: str = KIND_REALINEACION,
                   params: dict | None = None) -> None:
    _init_log(REBALANCES_LOG, REBAL_HEADER)
    params = params or {}
    with open(REBALANCES_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(timespec="seconds"), rebalance_id, trigger, kind,
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


def _place_orders_batch(
    conn: IBKRConnection,
    orders: list[dict],
    rebalance_id: str,
    reason: str = "rebalance",
    fill_timeout: float = 45.0,
    on_progress=None,
) -> tuple[list, int, int]:
    """Dispara TODAS las órdenes de mercado de una y espera los fills UNA sola vez.

    placeOrder() no bloquea, así que mandamos todo en ráfaga y recién después
    esperamos que llenen. Pasa de ~minutos (orden por orden) a ~segundos.

    on_progress(msg): callback opcional para reportar progreso a la UI.
    Devuelve (placed, n_filled, n_pending)."""
    def _p(msg):
        if on_progress:
            on_progress(msg)
    # Resolver el contrato de cada orden: si viene el contrato EXACTO (cierre de
    # warrants/opciones) lo usamos ruteando por SMART; si no, construimos Stock.
    resolved = []  # (contract, order_dict)
    to_qualify = []
    for o in orders:
        c = o.get("contract")
        if c is not None:
            c.exchange = "SMART"
        else:
            c = Stock(o["ticker"], "SMART", "USD")
            to_qualify.append(c)
        resolved.append((c, o))
    if to_qualify:
        conn.ib.qualifyContracts(*to_qualify)

    # Disparar todas (sin esperar fill entre una y otra). Pausa breve cada 40 para
    # no pasar el rate limit de IBKR (~50 mensajes/seg) y evitar pacing violations.
    _p(f"Enviando {len(orders)} órdenes a IBKR…")
    placed = []
    for i, (c, o) in enumerate(resolved):
        order = MarketOrder(o["action"], abs(o["qty"]))
        order.tif = "DAY"  # evita el error 10349 del preset de TWS
        trade = conn.ib.placeOrder(c, order)
        placed.append((trade, o))
        if (i + 1) % 40 == 0:
            conn.ib.sleep(1)

    # Esperar a que todas terminen (llenen/cancelen), una sola espera acotada.
    _p(f"{len(placed)} órdenes enviadas. Esperando ejecución…")
    done = ("Filled", "Cancelled", "ApiCancelled", "Inactive")
    waited = 0.0
    last_nf = -1
    while waited < fill_timeout and not all(t.orderStatus.status in done for t, _ in placed):
        conn.ib.sleep(0.5)
        waited += 0.5
        nf = sum(t.orderStatus.status == "Filled" for t, _ in placed)
        if nf != last_nf:           # reportar avance solo cuando cambia
            _p(f"Ejecutando… {nf}/{len(placed)} órdenes llenadas")
            last_nf = nf

    # Registrar cada orden con su estado/fill final y acumular el flujo de caja neto
    # (compras − ventas, a precio de fill) para el P&L acumulado real.
    n_filled = 0
    net_cash_flow = 0.0
    for trade, o in placed:
        status = trade.orderStatus.status
        fill_price = trade.orderStatus.avgFillPrice or ""
        n_filled += int(status == "Filled")
        filled_qty = trade.orderStatus.filled or 0
        if fill_price and filled_qty:
            sign = 1.0 if o["action"] == "BUY" else -1.0   # compra = sale caja
            net_cash_flow += sign * float(filled_qty) * float(fill_price)
        _log_trade(rebalance_id, o["ticker"], o["action"], o["qty"], "MKT", None,
                   fill_price, status, reason)
    if net_cash_flow:
        state.add_cash_flow(net_cash_flow)
    n_pending = len(placed) - n_filled
    print(f"  Fills: {n_filled}/{len(placed)} llenadas en {waited:.0f}s")
    return placed, n_filled, n_pending


def execute_rebalance(
    conn: IBKRConnection,
    target_weights: pd.Series,
    capital: float,
    dry_run: bool = False,
    trigger: str = "manual",
    params: dict | None = None,
    on_progress=None,
    kind: str = KIND_REALINEACION,
) -> dict:
    """
    Computa las órdenes necesarias para alcanzar target_weights y las ejecuta.

    target_weights: Series índice = tickers, valores = pesos objetivo [-1, 1]
    capital: valor total del portafolio en USD
    dry_run: si True, solo computa las órdenes sin ejecutarlas ni registrarlas
    trigger: origen del rebalanceo (ej. "manual", "dashboard") — para el log
    kind: QUÉ tipo de ejecución es (ver KIND_*). Distingue OPERAR de REBALANCEAR:
          solo allocación inicial y rebalanceo mensual avanzan el reloj mensual; una
          realineación / liquidación / test NO consumen el rebalanceo del mes. Default
          conservador = realineacion (no marca el mes) para no pisar el calendario.
    on_progress(msg): callback opcional para reportar el avance a la UI.

    Devuelve un dict: {orders, skipped, n_filled, n_pending, gross_notional, rebalance_id}.
    'skipped' = posiciones objetivo que daban < 1 acción (no se pueden operar enteras).
    """
    def _p(msg):
        if on_progress:
            on_progress(msg)

    if not dry_run and state.is_halted():
        raise RuntimeError(
            "Estrategia CORTADA (halted). Reanudá la estrategia antes de operar.")

    rebalance_id = _new_rebalance_id("RB")
    _p("Leyendo posiciones actuales…")
    # Cantidades actuales de forma CONFIABLE (reqPositions + espera), agregadas por
    # símbolo. CLAVE para netear bien: NO usamos el market_value del stream de cuenta,
    # que en una conexión recién abierta puede no estar listo y haría que el rebalanceo
    # crea la cuenta VACÍA y recompre todo el target → apilando posiciones (bug que
    # infló la exposición a ~10×). reqPositions siempre devuelve las cantidades reales.
    current_qty: dict[str, float] = {}
    if not dry_run and conn is not None:
        for p in conn.get_raw_positions():
            current_qty[p["symbol"]] = current_qty.get(p["symbol"], 0.0) + p["qty"]

    # Precios del parquet LOCAL para valuar y dimensionar (instantáneo, sin red).
    # Evita yfinance (lento y con la fecha futura del entorno falla).
    prices: dict[str, float] = dict(_parquet_last_prices(list(target_weights.index)))

    orders = []
    skipped = []   # posiciones objetivo que dan < 1 acción (no operables enteras)
    print(f"\n{'-'*55}")
    print(f"  Rebalanceo {rebalance_id} {'(DRY RUN) ' if dry_run else ''}— Capital: ${capital:,.0f}")
    print(f"{'-'*55}")
    _p("Calculando órdenes objetivo…")

    for ticker, w_target in target_weights.items():
        target_value = w_target * capital

        price = prices.get(ticker)
        # Precio inválido (faltante / 0 / NaN): caemos a yfinance como último recurso
        # (el fill real es a mercado igual).
        if price is None or price != price or price <= 0:
            try:
                price = _yf_price(ticker)
            except Exception:
                price = 0.0
            prices[ticker] = price

        if not price or price != price or price <= 0:
            continue

        # Valuar la posición actual con el MISMO precio del parquet (consistente con el
        # target) → delta = lo que falta comprar/vender para llegar al objetivo.
        current_value = current_qty.get(ticker, 0.0) * price
        delta_value = target_value - current_value
        qty = delta_value / price
        if abs(qty) < 1:
            # Daría menos de 1 acción: no se puede operar entera, se omite.
            skipped.append({"ticker": ticker, "target_w": round(float(w_target), 4),
                            "qty_estimada": round(abs(qty), 3), "precio": round(price, 2)})
            continue

        action: Literal["BUY", "SELL"] = "BUY" if qty > 0 else "SELL"
        order = {"ticker": ticker, "action": action, "qty": round(abs(qty)),
                 "price": round(price, 2), "delta_usd": round(delta_value)}
        orders.append(order)

        if dry_run:
            print(f"  {action:4} {round(abs(qty)):6} {ticker:6}  @ ~{price:.2f}  "
                  f"(D${delta_value:+,.0f})")

    if skipped:
        _p(f"{len(orders)} órdenes a ejecutar · {len(skipped)} omitidas (daban < 1 acción).")

    # Ejecución EN LOTE: dispara todas las órdenes de una y espera los fills una
    # sola vez (en vez de orden-por-orden, que tardaba minutos).
    n_filled = n_pending = 0
    if not dry_run and orders:
        _, n_filled, n_pending = _place_orders_batch(
            conn, orders, rebalance_id, reason="rebalance", on_progress=on_progress)

    gross_notional = sum(abs(o["qty"] * o["price"]) for o in orders)
    print(f"{'-'*55}")
    print(f"  Total órdenes: {len(orders)}  ·  Nocional bruto: ${gross_notional:,.0f}")

    if not dry_run and orders:
        _log_rebalance(rebalance_id, trigger, len(orders), gross_notional, capital,
                       status="executed", kind=kind, params=params)
        # Avanzar el reloj mensual SOLO si esta ejecución es realmente un rebalanceo
        # (mensual o allocación inicial). Operar por otro motivo —realinear drift,
        # liquidar, un test— NO debe marcar el mes como rebalanceado: operar ≠ rebalancear.
        if kind in _KINDS_QUE_MARCAN_MES:
            state.record_rebalance(rebalance_id)
        _p(f"✓ Listo: {n_filled}/{len(orders)} órdenes llenadas"
           + (f" · {n_pending} sin confirmar" if n_pending else " · nada pendiente"))
    return {"orders": orders, "skipped": skipped, "n_filled": n_filled,
            "n_pending": n_pending, "gross_notional": gross_notional,
            "rebalance_id": rebalance_id}


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
        if closeable:
            _place_orders_batch(conn, closeable, rebalance_id, reason=reason)
        _log_rebalance(rebalance_id, trigger="KILL", n_orders=len(closeable),
                       gross_notional=0.0, capital=0.0, status="executed",
                       kind=KIND_LIQUIDACION)
    else:
        for o in closeable:
            print(f"  {o['action']:4} {o['qty']:>6g} {o['ticker']:6} [{o['secType']}]  [cerrar]")

    print(f"{'='*55}")
    # Devolvemos sin el objeto contract (no serializable) para el dashboard/logs.
    return [{k: v for k, v in o.items() if k != "contract"} for o in (closeable + fractional)]
