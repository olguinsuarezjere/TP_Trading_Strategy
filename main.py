import subprocess
import sys

# Force UTF-8 on Windows terminals (cp1252 doesn't support Spanish/box chars)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import yaml
import click

from src.data.loader import load_returns, update_prices
from src.data.universe import ETF_UNIVERSE
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
@click.pass_context
def execute(ctx, dry_run):
    """Calcula el rebalanceo y ejecuta las órdenes en IBKR (o simula con --dry-run)."""
    from src.broker.ibkr import IBKRConnection
    from src.broker.orders import execute_rebalance

    config = _load_config(ctx.obj["config_path"])
    returns = load_returns(config)

    # Calcular pesos target para el mes actual
    from src.strategy.portfolio import build_portfolio
    weights, _ = build_portfolio(returns, config)
    target_weights = weights.iloc[-1].dropna()
    target_weights = target_weights[target_weights != 0]

    if dry_run:
        click.secho("DRY RUN — no se ejecutarán órdenes reales.", fg="yellow")
        conn = IBKRConnection.__new__(IBKRConnection)
        conn.ib = None
        execute_rebalance(conn, target_weights, capital=1_000_000, dry_run=True)
        return

    broker = config["broker"]
    conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
    try:
        conn.connect()
        account = conn.get_account_summary()
        capital = account.get("NetLiquidation", 1_000_000)
        click.echo(f"Capital disponible: ${capital:,.2f}")
        execute_rebalance(conn, target_weights, capital=capital, dry_run=False)
    finally:
        conn.disconnect()


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
