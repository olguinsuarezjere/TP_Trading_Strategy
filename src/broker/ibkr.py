import asyncio
import time

import pandas as pd


def _ensure_event_loop() -> None:
    """Garantiza que el HILO ACTUAL tenga un asyncio event loop usable.

    ib_insync (vía eventkit) requiere un event loop en el hilo donde se instancia/
    conecta IB(). En el ScriptRunner de Streamlit —un hilo distinto al principal y al
    que importó este módulo— no hay loop, y conectar explota con
    'There is no current event loop in thread ...'. Hay que crearlo en RUNTIME, en el
    hilo actual, no solo al importar."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


# Al importar (cubre el hilo de import); en __init__ se vuelve a asegurar por-hilo.
_ensure_event_loop()

from ib_insync import IB, Stock, util  # noqa: E402


def _classify_conn_error(e: Exception) -> str:
    """Clasifica un fallo de conexión: 'refused' (TWS apagado/puerto cerrado = real),
    'timeout' (TWS ocupado, transitorio), 'clientid' (id tomado, transitorio) u 'other'."""
    msg = str(e).lower()
    if isinstance(e, ConnectionRefusedError) or "refused" in msg:
        return "refused"
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)) or "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "client id is already in use" in msg or "clientid" in msg or "326" in msg:
        return "clientid"
    return "other"


def _user_conn_message(host: str, port: int, kind: str, e: Exception) -> str:
    """Mensaje claro al usuario según el tipo de fallo, ya agotados los reintentos."""
    base = f"No se pudo conectar a TWS en {host}:{port}"
    if kind == "refused":
        return (f"{base}: la conexión fue rechazada. Probablemente TWS o IB Gateway no "
                f"esté abierto, o la API no esté habilitada en el puerto {port}. "
                f"Abrí TWS y activá la API (Global Configuration → API → Settings).")
    if kind == "timeout":
        return (f"{base}: TWS no respondió tras varios intentos. Puede estar iniciando o "
                f"re-autenticándose, o falta aceptar la conexión entrante / agregar "
                f"127.0.0.1 a Trusted IPs. Esperá unos segundos y reintentá.")
    if kind == "clientid":
        return (f"{base}: el clientId quedó tomado por una sesión anterior que no cerró. "
                f"Esperá unos segundos a que TWS lo libere y reintentá.")
    return f"{base}. Asegurate de que TWS o IB Gateway esté corriendo. Error: {e}"


class IBKRConnection:
    """
    Wrapper sobre ib_insync para conectarse a TWS Paper Trading.

    Uso:
        conn = IBKRConnection()
        conn.connect()
        positions = conn.get_positions()
        conn.disconnect()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        # Asegurar el event loop en ESTE hilo antes de crear IB() (clave para el
        # ScriptRunner de Streamlit, que corre en un hilo sin loop).
        _ensure_event_loop()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()

    def connect(self, retries: int = 3, timeout: float = 7.0) -> None:
        """Conecta a TWS de forma robusta.

        Reintenta los fallos TRANSITORIOS (handshake lento porque TWS está ocupado o
        re-autenticándose; o el clientId todavía tomado por una sesión anterior que no
        cerró limpio). Solo levanta un error al usuario cuando, tras agotar los
        reintentos, la conexión realmente no se pudo establecer — típicamente porque
        TWS/IB Gateway no está abierto o la API no está habilitada en el puerto."""
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=timeout)
                self._verify_connection()
                return
            except Exception as e:
                last_err = e
                kind = _classify_conn_error(e)
                # Dejar el socket limpio antes de reintentar.
                try:
                    if self.ib.isConnected():
                        self.ib.disconnect()
                except Exception:
                    pass
                if attempt < retries:
                    # clientId tomado por una sesión vieja: probar con uno alternativo.
                    if kind == "clientid":
                        self.client_id += 100
                    print(f"[IBKR] intento {attempt}/{retries} falló ({kind}); reintentando…")
                    time.sleep(min(1.0 * attempt, 3.0))  # backoff incremental
                    continue
                # Reintentos agotados -> error real al usuario.
                raise ConnectionError(_user_conn_message(self.host, self.port, kind, e))

    def _verify_connection(self) -> None:
        if not self.ib.isConnected():
            raise ConnectionError("Conexión fallida: TWS no respondió.")
        accounts = self.ib.managedAccounts()
        server_v = self.ib.client.serverVersion()
        print(f"[OK] Conectado a IBKR TWS en {self.host}:{self.port}")
        print(f"     Cuenta(s)  : {', '.join(accounts)}")
        print(f"     Servidor   : v{server_v}")
        # Datos diferidos (tipo 3) — disponibles sin suscripción en cuentas paper
        self.ib.reqMarketDataType(3)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()
            print("Desconectado de IBKR TWS")

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    def get_connection_info(self) -> dict:
        """Info de la conexión para el panel de estado: cuenta(s), versión de servidor."""
        accounts = list(self.ib.managedAccounts())
        return {
            "connected":      self.ib.isConnected(),
            "accounts":       accounts,
            "account":        accounts[0] if accounts else "—",
            "server_version": self.ib.client.serverVersion() if self.ib.isConnected() else None,
            "host":           self.host,
            "port":           self.port,
        }

    def get_account_summary(self) -> dict:
        """Retorna valores clave de la cuenta: cash, net liquidation, unrealized PnL."""
        summary = self.ib.accountSummary()
        result = {}
        for item in summary:
            if item.tag in ("NetLiquidation", "TotalCashValue", "UnrealizedPnL", "RealizedPnL"):
                result[item.tag] = float(item.value)
        return result

    def get_positions(self) -> pd.DataFrame:
        """Retorna las posiciones actuales como DataFrame, agregadas por ticker."""
        positions = self.ib.positions()
        if not positions:
            return pd.DataFrame(columns=["ticker", "qty", "avg_cost", "market_price", "market_value"])

        # Agregar por ticker (TWS puede reportar múltiples lotes por símbolo)
        aggregated: dict[str, dict] = {}
        for pos in positions:
            ticker = pos.contract.symbol
            if ticker not in aggregated:
                aggregated[ticker] = {"qty": 0.0, "cost_basis": 0.0, "contract": pos.contract}
            aggregated[ticker]["qty"] += pos.position
            aggregated[ticker]["cost_basis"] += pos.position * pos.avgCost

        rows = []
        for ticker, data in aggregated.items():
            qty = data["qty"]
            avg_cost = data["cost_basis"] / qty if qty != 0 else 0.0
            contract = Stock(ticker, "SMART", "USD")
            self.ib.qualifyContracts(contract)
            ticker_data = self.ib.reqMktData(contract, "", False, False)
            self.ib.sleep(1.0)
            price = ticker_data.last if ticker_data.last and ticker_data.last > 0 else avg_cost
            rows.append({
                "ticker":       ticker,
                "qty":          qty,
                "avg_cost":     avg_cost,
                "market_price": price,
                "market_value": qty * price,
            })
        return pd.DataFrame(rows)

    def validate_tradeable(
        self,
        tickers: list[str],
        exchange: str = "SMART",
        currency: str = "USD",
        pause: float = 0.05,
    ) -> dict[str, tuple[bool, str]]:
        """
        Verifica qué tickers son operables en IBKR vía SMART routing en USD.

        Para cada ticker pide la definición de contrato (reqContractDetails). Si
        IBKR devuelve al menos una definición -> operable. Si no -> no operable
        (delisted, no disponible en la cuenta, o símbolo inexistente).

        Devuelve {ticker: (operable, detalle)}.
        """
        results: dict[str, tuple[bool, str]] = {}
        for t in tickers:
            contract = Stock(t, exchange, currency)
            try:
                details = self.ib.reqContractDetails(contract)
            except Exception as e:
                results[t] = (False, f"error: {e}")
                self.ib.sleep(pause)
                continue
            if not details:
                results[t] = (False, "sin definición de contrato en IBKR")
            else:
                d = details[0]
                primary = d.contract.primaryExchange or exchange
                name = (d.longName or "").strip()
                results[t] = (True, f"{primary}{' · ' + name if name else ''}")
            self.ib.sleep(pause)
        return results

    def get_market_price(self, ticker: str) -> float:
        """Último precio de mercado para un ticker. Devuelve 0.0 si no hay dato válido.

        Ojo: `nan or x` devuelve nan (nan es truthy), por eso filtramos NaN/<=0
        explícitamente en vez de usar `last or close or 0`."""
        contract = Stock(ticker, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        ticker_data = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(0.5)
        for p in (ticker_data.last, ticker_data.close):
            if p is not None and p == p and p > 0:  # p == p excluye NaN
                return float(p)
        return 0.0

    def get_positions_simple(self) -> pd.DataFrame:
        """Posiciones (ticker, qty, avg_cost) SIN pedir market data — rápido.

        Útil para el corte/flatten, donde solo importa cuánto hay que cerrar.
        Agrega por símbolo por si TWS reporta varios lotes.
        """
        agg: dict[str, dict] = {}
        for pos in self.ib.positions():
            sym = pos.contract.symbol
            d = agg.setdefault(sym, {"qty": 0.0, "cost_basis": 0.0})
            d["qty"] += pos.position
            d["cost_basis"] += pos.position * pos.avgCost
        rows = [
            {"ticker": s, "qty": d["qty"],
             "avg_cost": (d["cost_basis"] / d["qty"]) if d["qty"] else 0.0}
            for s, d in agg.items()
        ]
        return pd.DataFrame(rows, columns=["ticker", "qty", "avg_cost"])

    def get_portfolio_fast(self, settle: float = 2.0, load_timeout: float = 8.0) -> pd.DataFrame:
        """Portafolio completo (precio, valor de mercado, P&L) en UNA sola llamada.

        Usa `ib.portfolio()` (viene del stream de actualizaciones de cuenta de TWS),
        en vez de pedir `reqMktData` ticker por ticker con pausa. Para 100+ posiciones
        esto pasa de ~minutos a ~2 segundos. TWS calcula el marketPrice (datos
        demorados si no hay suscripción en tiempo real).

        NO llamamos reqAccountUpdates(): ib_insync ya auto-suscribe las actualizaciones
        de cuenta al conectar, así que ib.portfolio() ya está poblado. Llamar
        reqAccountUpdates() con cuenta única y account='' se CUELGA esperando un
        accountDownloadEnd que no llega.

        Espera ADAPTATIVA: en vez de dormir `settle` fijo, espera solo hasta que lleguen
        los datos de cuenta (señal de que el download terminó), con ese tope. Como
        connect() ya sincroniza la cuenta, normalmente sale al instante.

        Espera de COMPLETITUD (clave tras operar): el stream de cuenta entrega las
        posiciones de a poco. Si valuamos a mitad de carga, el market value sale
        INCOMPLETO y el P&L (= market value − net_deployed) muestra un valor falso —el
        "-25.000" fantasma que se corrige solo en el refresh siguiente—. reqPositions()
        da el set COMPLETO y confiable; esperamos a que portfolio() (que trae el market
        value) cubra a TODAS esas posiciones con precio, o hasta `load_timeout`."""
        waited = 0.0
        while waited < settle and not self.ib.accountValues():
            self.ib.sleep(0.2)
            waited += 0.2

        # 1) Set completo de posiciones esperadas (esperar a que reqPositions se estabilice).
        self.ib.reqPositions()
        prev_n, t = -1, 0.0
        while t < 3.0:
            self.ib.sleep(0.3); t += 0.3
            n = sum(1 for p in self.ib.positions() if abs(p.position) > 1e-9)
            if n == prev_n:            # dos lecturas iguales -> estable
                break
            prev_n = n
        expected = {p.contract.conId for p in self.ib.positions() if abs(p.position) > 1e-9}

        # 2) Esperar a que el stream de portfolio cubra todas esas posiciones CON precio
        #    (market value no nulo). Si una posición no se puede valuar (sin datos), el
        #    tope evita colgarse y devuelve lo mejor disponible.
        if expected:
            t = 0.0
            while t < load_timeout:
                priced = {it.contract.conId for it in self.ib.portfolio()
                          if abs(it.position) > 1e-9 and it.marketValue}
                if expected <= priced:
                    break
                self.ib.sleep(0.3); t += 0.3

        rows = []
        for it in self.ib.portfolio():
            if abs(it.position) < 1e-9:
                continue
            rows.append({
                "ticker":         it.contract.symbol,
                "sec_type":       it.contract.secType,
                "qty":            it.position,
                "avg_cost":       it.averageCost,
                "market_price":   it.marketPrice,
                "market_value":   it.marketValue,
                "unrealized_pnl": it.unrealizedPNL,
            })
        return pd.DataFrame(rows, columns=[
            "ticker", "sec_type", "qty", "avg_cost", "market_price",
            "market_value", "unrealized_pnl"])

    def get_raw_positions(self, settle: float = 3.0) -> list:
        """Posiciones abiertas con su CONTRATO EXACTO (conId, secType), SIN agregar
        por símbolo.

        Clave para el kill switch: un mismo símbolo puede tener varios instrumentos
        (p.ej. la acción OPEN y warrants de OPEN). Agregar por símbolo y reconstruir
        un Stock haría operar el instrumento equivocado. Acá devolvemos el contrato
        real de cada lote.

        Pide reqPositions y espera `settle` segundos porque ib.positions() puede venir
        incompleto justo después de conectar.
        """
        self.ib.reqPositions()
        self.ib.sleep(settle)
        out = []
        for p in self.ib.positions():
            if abs(p.position) < 1e-9:
                continue
            out.append({
                "contract": p.contract,
                "symbol":   p.contract.symbol,
                "secType":  p.contract.secType,
                "qty":      p.position,
                "avg_cost": p.avgCost,
            })
        return out

    def get_open_orders(self) -> pd.DataFrame:
        """Órdenes abiertas (pendientes) en la cuenta."""
        rows = []
        for t in self.ib.openTrades():
            rows.append({
                "order_id": t.order.orderId,
                "ticker":   t.contract.symbol,
                "action":   t.order.action,
                "qty":      t.order.totalQuantity,
                "type":     t.order.orderType,
                "status":   t.orderStatus.status,
            })
        return pd.DataFrame(rows, columns=["order_id", "ticker", "action", "qty", "type", "status"])

    def cancel_all_orders(self) -> None:
        """Cancela todas las órdenes abiertas (global cancel)."""
        self.ib.reqGlobalCancel()
        self.ib.sleep(1)
