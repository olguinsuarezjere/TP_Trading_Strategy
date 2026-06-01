# ---------------------------------------------
# Codigo estrategia + IBKR
# ---------------------------------------------

import subprocess
import sys

# Force UTF-8 on Windows terminals (cp1252 doesn't support Spanish/box chars)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import yaml
import click

# NOTA: los imports del broker (ib_insync) son lazy — se cargan dentro de los
# comandos que conectan a IBKR (test-connection / monitor / execute). Así
# `dashboard` y `backtest` funcionan aunque ib_insync no esté instalado.
from src.strategy.portfolio import build_portfolio
from src.data.loader import load_returns, update_prices, data_status
from src.data.universe import ETF_UNIVERSE, ASSET_CLASSES
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import print_report
from src.robustness.sensitivity import lookback_sensitivity, target_vol_sensitivity, cost_sensitivity
from src.robustness.stress_test import analyze_crisis_performance, worst_drawdowns
from src.robustness.out_of_sample import walk_forward, expanding_window


def _load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _apply_overrides(config: dict, **kwargs) -> dict:
    """Aplica overrides de CLI sobre config.yaml."""
    if kwargs.get("lookback"):
        config["strategy"]["lookback_months"] = kwargs["lookback"]
    if kwargs.get("target_vol"):
        config["strategy"]["target_volatility"] = kwargs["target_vol"]
    if kwargs.get("start"):
        config["backtest"]["start_date"] = kwargs["start"]
    if kwargs.get("end"):
        config["backtest"]["end_date"] = kwargs["end"]
    return config


@click.group()
@click.option("--config", default="config.yaml", help="Path al archivo de configuración.")
@click.pass_context
def cli(ctx, config):
    """Sistema de Trading TSMOM — Ingeniería Financiera F414\n
    Documentación: python main.py <comando> --help"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


# ---------------------------------------------
# update-data
# ---------------------------------------------
@cli.command("update-data")
@click.pass_context
def update_data(ctx):
    """Descarga precios actualizados de yfinance y actualiza el parquet."""
    config = _load_config(ctx.obj["config_path"])
    path = config["data"]["path"]
    tickers = list(ETF_UNIVERSE.keys())
    click.echo(f"Actualizando {len(tickers)} ETFs en {path} ...")
    update_prices(path, tickers)
    click.secho("Datos actualizados.", fg="green")


# ---------------------------------------------
# data-status
# ---------------------------------------------
@cli.command("data-status")
@click.pass_context
def data_status_cmd(ctx):
    """Muestra la consistencia entre universe.py y el parquet (y la cobertura)."""
    config = _load_config(ctx.obj["config_path"])
    st = data_status(config)

    click.secho("== Consistencia universo <-> parquet ==", bold=True)
    click.echo(f"  Universo (universe.py): {st['n_universe']} ETFs")
    click.echo(f"  Columnas en parquet:    {st['n_parquet']}")
    if st["window"]:
        click.echo(f"  Ventana backtest:       {st['window'][0]:%Y-%m} a {st['window'][1]:%Y-%m}")

    if st["missing"]:
        click.secho(f"\n  [!] En universo SIN datos ({len(st['missing'])}): "
                    f"{st['missing']}", fg="red")
        click.echo("      -> correr: python scripts/fetch_missing_etfs.py")
    else:
        click.secho("\n  [OK] Todos los ETFs del universo tienen datos.", fg="green")

    if st["orphans"]:
        click.secho(f"\n  [!] En parquet pero NO en universo ({len(st['orphans'])}): "
                    f"{st['orphans']}", fg="yellow")
        click.echo("      (datos huérfanos: descargados pero ignorados por el backtest)")
    else:
        click.secho("  [OK] No hay columnas huérfanas en el parquet.", fg="green")

    if st.get("redundant_present"):
        click.secho(f"\n  [i] Redundantes por curación de liquidez (corr>=0.95), "
                    f"datos en parquet pero fuera del universo activo "
                    f"({len(st['redundant_present'])}): {st['redundant_present']}", fg="cyan")
        click.echo("      (ver REDUNDANT_TICKERS en universe.py; vaciar ese dict para volver a los 205)")

    if st["insufficient"]:
        click.secho(f"\n  [!] Sin historia suficiente (<{st['min_history']} meses), "
                    f"el loader los descarta ({len(st['insufficient'])}): "
                    f"{st['insufficient']}", fg="red")

    if st["late"]:
        click.secho(f"\n  [i] Incluidos desde su inception (arrancan después de "
                    f"{st['window'][0]:%Y-%m}) ({len(st['late'])}):", fg="cyan")
        for t in sorted(st["late"], key=lambda x: st["inception"][x]):
            click.echo(f"      {t:6} desde {st['inception'][t]:%Y-%m}  "
                       f"({st['coverage'][t]:.0f}% de la ventana)")

    click.secho(f"\n  ETFs activos en el backtest: {len(st['active'])}", bold=True)

    click.secho("\n== Composición por clase de activo ==", bold=True)
    for ac in ASSET_CLASSES:
        n = sum(1 for t in st["active"] if ETF_UNIVERSE.get(t) == ac)
        click.echo(f"  {ac:11} {n:3} ETFs")


# ---------------------------------------------
# backtest
# ---------------------------------------------
@cli.command("backtest")
@click.option("--lookback",    default=None, type=int,   help="Meses de lookback (default: config.yaml)")
@click.option("--target-vol",  default=None, type=float, help="Volatilidad objetivo anual (default: config.yaml)")
@click.option("--start",       default=None, type=str,   help="Fecha de inicio YYYY-MM-DD")
@click.option("--end",         default=None, type=str,   help="Fecha de fin YYYY-MM-DD")
@click.option("--signal",      default="binary", type=click.Choice(["binary", "strength"]),
              help="Tipo de señal: binary (Moskowitz) o strength (Baz et al.)")
@click.pass_context
def backtest(ctx, lookback, target_vol, start, end, signal):
    """Corre el backtest histórico y muestra las métricas de performance."""
    config = _load_config(ctx.obj["config_path"])
    config = _apply_overrides(config, lookback=lookback, target_vol=target_vol, start=start, end=end)

    click.echo("Cargando datos ...")
    returns = load_returns(config)
    click.echo(f"  Universo: {returns.shape[1]} ETFs | {returns.shape[0]} meses "
               f"({returns.index[0].strftime('%Y-%m')} a {returns.index[-1].strftime('%Y-%m')})")

    click.echo("Corriendo backtest ...")
    engine = BacktestEngine(config)
    results = engine.run(returns, use_signal_strength=(signal == "strength"))

    title = (f"TSMOM [{signal}] | lookback={config['strategy']['lookback_months']}m | "
             f"target_vol={config['strategy']['target_volatility']:.0%}")
    print_report(results.metrics, title=title)


# ---------------------------------------------
# robustness
# ---------------------------------------------
@cli.command("robustness")
@click.option("--test", default="all",
              type=click.Choice(["all", "sensitivity", "stress", "oos"]),
              help="Qué test correr.")
@click.pass_context
def robustness(ctx, test):
    """Corre los tests de robustez: sensibilidad, stress y out-of-sample."""
    config = _load_config(ctx.obj["config_path"])
    returns = load_returns(config)
    engine = BacktestEngine(config)
    results = engine.run(returns)

    if test in ("all", "sensitivity"):
        click.secho("\n-- Sensibilidad al Lookback --", bold=True)
        lb = lookback_sensitivity(returns, config)
        click.echo(lb.round(2).to_string())

        click.secho("\n-- Sensibilidad al Target Vol --", bold=True)
        tv = target_vol_sensitivity(returns, config)
        click.echo(tv.round(2).to_string())

        click.secho("\n-- Sensibilidad a Costos --", bold=True)
        cs = cost_sensitivity(returns, config)
        click.echo(cs.round(2).to_string())

    if test in ("all", "stress"):
        click.secho("\n-- Stress Test — Períodos de Crisis --", bold=True)
        crisis = analyze_crisis_performance(results.portfolio_returns)
        click.echo(crisis.to_string())

        click.secho("\n-- Peores Drawdowns --", bold=True)
        dd = worst_drawdowns(results.portfolio_returns)
        click.echo(dd.to_string(index=False))

    if test in ("all", "oos"):
        click.secho("\n-- Out-of-Sample (Walk-Forward) --", bold=True)
        wf = walk_forward(returns, config)
        click.echo(wf.round(2).to_string(index=False))

        click.secho("\n-- In-Sample vs Out-of-Sample --", bold=True)
        oos = expanding_window(returns, config)
        click.echo(oos.round(2).to_string())


# ---------------------------------------------
# test-connection
# ---------------------------------------------
@cli.command("test-connection")
@click.pass_context
def test_connection(ctx):
    """Verifica la conexión con IBKR TWS sin ejecutar órdenes."""
    from src.broker.ibkr import IBKRConnection
    config = _load_config(ctx.obj["config_path"])
    broker = config["broker"]

    click.echo(f"Conectando a IBKR TWS en {broker['host']}:{broker['port']} ...")
    conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
    try:
        conn.connect()

        click.secho("\n[1] Resumen de cuenta:", bold=True)
        account = conn.get_account_summary()
        for key, value in account.items():
            click.echo(f"    {key:<25} ${value:>14,.2f}")

        click.secho("\n[2] Posiciones actuales:", bold=True)
        positions = conn.get_positions()
        if positions.empty:
            click.echo("    Sin posiciones abiertas.")
        else:
            click.echo(positions.to_string(index=False))

        click.secho("\nConexion OK — todo funciona correctamente.", fg="green")
    except Exception as e:
        click.secho(f"\nError de conexion: {e}", fg="red")
    finally:
        conn.disconnect()


# ---------------------------------------------
# validate-ibkr
# ---------------------------------------------
@cli.command("validate-ibkr")
@click.option("--out", default="logs/ibkr_validation.csv", type=str,
              help="CSV donde guardar el resultado por ticker.")
@click.pass_context
def validate_ibkr(ctx, out):
    """Verifica contra IBKR qué ETFs del universo son realmente operables."""
    import csv
    from pathlib import Path
    from src.broker.ibkr import IBKRConnection
    config = _load_config(ctx.obj["config_path"])
    broker = config["broker"]
    tickers = list(ETF_UNIVERSE.keys())

    click.echo(f"Conectando a IBKR TWS en {broker['host']}:{broker['port']} ...")
    conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
    try:
        conn.connect()
        click.echo(f"Validando {len(tickers)} ETFs contra IBKR (SMART/USD) ...")
        results = conn.validate_tradeable(tickers)
    finally:
        conn.disconnect()

    ok = [t for t in tickers if results.get(t, (False, ""))[0]]
    bad = [t for t in tickers if not results.get(t, (False, ""))[0]]

    if bad:
        click.secho(f"\n[!] NO operables ({len(bad)}):", fg="red", bold=True)
        for t in bad:
            click.echo(f"    {t:6} {results[t][1]}  [{ETF_UNIVERSE.get(t)}]")
    else:
        click.secho("\n[OK] Todos los ETFs del universo son operables en IBKR.", fg="green")

    click.secho(f"\nOperables: {len(ok)} / {len(tickers)}", bold=True)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "asset_class", "tradeable", "detail"])
        for t in tickers:
            tradeable, detail = results.get(t, (False, "no consultado"))
            w.writerow([t, ETF_UNIVERSE.get(t), int(tradeable), detail])
    click.secho(f"Resultado guardado en {out}", fg="cyan")

    if bad:
        click.echo("\nPara dejar el universo solo con lo operable, quitar de "
                   "universe.py:\n  " + str(bad))


# ---------------------------------------------
# monitor
# ---------------------------------------------
@cli.command("monitor")
@click.option("--interval", default=30, type=int, help="Segundos entre actualizaciones.")
@click.pass_context
def monitor(ctx, interval):
    """Muestra el portafolio live conectándose a IBKR TWS."""
    from src.broker.ibkr import IBKRConnection
    from src.broker.monitor import stream_portfolio_updates
    config = _load_config(ctx.obj["config_path"])
    broker = config["broker"]

    click.echo(f"Conectando a IBKR TWS en {broker['host']}:{broker['port']} ...")
    conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
    try:
        conn.connect()
        stream_portfolio_updates(conn, interval_seconds=interval)
    finally:
        conn.disconnect()


# ---------------------------------------------
# execute
# ---------------------------------------------
@cli.command("execute")
@click.option("--dry-run", is_flag=True, default=False,
              help="Muestra las órdenes sin ejecutarlas.")
@click.option("--capital", default=None, type=float,
              help="Capital a destinar en USD (default: NetLiquidation completo). "
                   "Se acota al NetLiquidation real de la cuenta.")
@click.pass_context
def execute(ctx, dry_run, capital):
    """Calcula el rebalanceo y ejecuta las órdenes en IBKR (o simula con --dry-run)."""
    from src.broker.ibkr import IBKRConnection
    from src.broker.orders import execute_rebalance
    from src.broker.runner import compute_target_weights
    config = _load_config(ctx.obj["config_path"])
    returns = load_returns(config)

    # Misma fuente de pesos que el backtest y el dashboard (incluye vol scaling).
    target_weights = compute_target_weights(returns, config)

    if dry_run:
        click.secho("DRY RUN — no se ejecutarán órdenes reales.", fg="yellow")
        conn = IBKRConnection.__new__(IBKRConnection)
        conn.ib = None
        execute_rebalance(conn, target_weights, capital=capital or 1_000_000, dry_run=True)
        return

    broker = config["broker"]
    conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
    try:
        conn.connect()
        account = conn.get_account_summary()
        net_liq = account.get("NetLiquidation", 1_000_000)
        # Precaución: nunca desplegar más que lo pedido ni más que el NetLiquidation.
        deploy = min(capital, net_liq) if capital else net_liq
        click.echo(f"NetLiquidation: ${net_liq:,.2f}  ·  Capital a destinar: ${deploy:,.2f}")
        execute_rebalance(conn, target_weights, capital=deploy, dry_run=False)
    finally:
        conn.disconnect()


# ---------------------------------------------
# strategy-status / halt / resume
# ---------------------------------------------
@cli.command("strategy-status")
def strategy_status():
    """Muestra el estado de la estrategia (detenida / activa / pausada)."""
    from src.broker import state
    st = state.get_state()
    status = st.get("status", "stopped")
    chk = state.next_rebalance_date()
    if status == "running":
        click.secho("Estrategia: ACTIVA", fg="green", bold=True)
        click.echo(f"  enrolada:           {st.get('enrolled_at')}")
        click.echo(f"  parámetros:         {st.get('params')}")
        click.echo(f"  último rebalanceo:  {st.get('last_rebalance_at') or 'nunca'}")
        click.echo(f"  próximo rebalanceo: {chk.isoformat()}")
        if state.rebalance_due():
            click.secho("  [!] REBALANCEO PENDIENTE este mes -> python main.py tick", fg="yellow")
    elif status == "paused":
        click.secho("Estrategia: PAUSADA", fg="yellow", bold=True)
        click.echo(f"  desde:  {st.get('halted_at')}")
        click.echo(f"  motivo: {st.get('reason')}")
        click.echo("  -> reanudar con: python main.py resume")
    else:
        click.secho("Estrategia: DETENIDA (no enrolada)", fg="white", bold=True)
        click.echo("  -> iniciar con: python main.py start-strategy")


@cli.command("start-strategy")
@click.pass_context
def start_strategy_cmd(ctx):
    """Enrola la estrategia (status ACTIVA). El primer rebalanceo se ejecuta con 'tick'."""
    from src.broker import state
    config = _load_config(ctx.obj["config_path"])
    strat = config["strategy"]
    params = {"signal_mode": strat.get("signal_mode"),
              "lookback": strat.get("lookback_months"),
              "target_vol": strat.get("target_volatility")}
    state.start_strategy(params)
    click.secho("Estrategia ACTIVA.", fg="green", bold=True)
    click.echo(f"  parámetros: {params}")
    click.echo("  -> ejecutar el rebalanceo pendiente: python main.py tick")


@cli.command("halt")
@click.option("--reason", default="pausa manual (CLI)", help="Motivo de la pausa.")
def halt_cmd(reason):
    """Pausa la estrategia (bloquea rebalanceos). No cierra posiciones."""
    from src.broker import state
    state.pause(reason)
    click.secho("Estrategia PAUSADA. Los rebalanceos quedan bloqueados.", fg="yellow", bold=True)
    click.echo("Para cerrar posiciones además: python main.py close-all --execute")


@cli.command("resume")
def resume_cmd():
    """Reanuda la estrategia pausada (vuelve a permitir rebalanceos)."""
    from src.broker import state
    state.resume()
    click.secho("Estrategia REANUDADA (ACTIVA). Rebalanceos habilitados.", fg="green", bold=True)


# ---------------------------------------------
# tick  (el "termostato": chequea y, si toca, rebalancea)
# ---------------------------------------------
@cli.command("tick")
@click.option("--force", is_flag=True, default=False,
              help="Ejecuta el rebalanceo aunque no haya cambio de mes.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Solo muestra si toca rebalancear, sin ejecutar.")
@click.option("--capital", default=None, type=float,
              help="Capital a destinar en USD (default: NetLiquidation completo).")
@click.pass_context
def tick_cmd(ctx, force, dry_run, capital):
    """Chequea si toca rebalancear y, si toca (o --force), ejecuta. Apto para cron."""
    from src.broker import state
    from src.broker.runner import check_rebalance, run_tick
    from src.broker.ibkr import IBKRConnection
    config = _load_config(ctx.obj["config_path"])

    chk = check_rebalance()
    click.secho(f"Estado: {chk.status.upper()}", bold=True)
    click.echo(f"  {chk.reason}")
    click.echo(f"  próximo rebalanceo: {chk.next_rebalance_date}")

    if dry_run or (not chk.due and not force):
        if not chk.due and not force:
            click.secho("Nada que ejecutar.", fg="cyan")
        return

    if state.is_paused():
        click.secho("Estrategia PAUSADA: no se ejecuta.", fg="yellow")
        return

    returns = load_returns(config)
    broker = config["broker"]
    conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
    try:
        conn.connect()
        net_liq = conn.get_account_summary().get("NetLiquidation", 1_000_000)
        deploy = min(capital, net_liq) if capital else net_liq
        click.echo(f"NetLiquidation: ${net_liq:,.2f}  ·  Capital a destinar: ${deploy:,.2f}")
        result = run_tick(conn, returns, config, capital=deploy, force=force, trigger="cron")
    finally:
        conn.disconnect()
    click.secho(result.message, fg="green" if result.executed else "cyan")


# ---------------------------------------------
# close-all (kill switch)
# ---------------------------------------------
@cli.command("close-all")
@click.option("--execute", is_flag=True, default=False,
              help="Ejecuta el cierre REAL. Sin este flag es dry-run.")
@click.option("--halt/--no-halt", default=True,
              help="Detener la estrategia tras cerrar posiciones (default: sí).")
@click.pass_context
def close_all(ctx, execute, halt):
    """KILL SWITCH: cierra todas las posiciones en IBKR (dry-run por defecto)."""
    from src.broker.ibkr import IBKRConnection
    from src.broker.orders import close_all_positions
    from src.broker import state
    config = _load_config(ctx.obj["config_path"])
    broker = config["broker"]

    if not execute:
        click.secho("DRY RUN — no se cierra nada (usá --execute para ejecutar).", fg="yellow")
        conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
        try:
            conn.connect()
            close_all_positions(conn, dry_run=True)
        finally:
            conn.disconnect()
        return

    conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
    try:
        conn.connect()
        close_all_positions(conn, dry_run=False, reason="kill switch (CLI)")
    finally:
        conn.disconnect()
    if halt:
        state.halt("kill switch (CLI)")
        click.secho("Posiciones cerradas y estrategia CORTADA.", fg="red", bold=True)
    else:
        click.secho("Posiciones cerradas.", fg="green")


# ---------------------------------------------
# dashboard
# ---------------------------------------------
@cli.command("dashboard")
@click.option("--port", default=8501, type=int, help="Puerto para Streamlit.")
def dashboard(port):
    """Lanza el dashboard interactivo en el navegador (Streamlit)."""
    click.secho(f"Iniciando dashboard en http://localhost:{port} ...", fg="cyan")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        "src/dashboard/app.py",
        "--server.port", str(port),
        "--server.headless", "true",
    ])


if __name__ == "__main__":
    cli()
