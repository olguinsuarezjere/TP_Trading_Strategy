import os
import sys
import html
import yaml
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st

# Asegurar que el root del proyecto esté en el path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data.loader import load_returns
from src.data.universe import ETF_UNIVERSE, ASSET_CLASSES, ETF_INFO
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import (
    sharpe_ratio, sortino_ratio, annualized_return, annualized_volatility,
    max_drawdown, calmar_ratio, hit_rate, turnover,
)
from src.robustness.sensitivity import (
    lookback_sensitivity, target_vol_sensitivity, cost_sensitivity, optimize_sharpe,
)
from src.robustness.stress_test import analyze_crisis_performance, CRISIS_PERIODS
from src.robustness.out_of_sample import walk_forward, expanding_window
from src.strategy.signals import compute_tsmom_signal, compute_signal_strength
from src.strategy.volatility import compute_ex_ante_vol
from src.dashboard import theme as T

# ============================================================ CONFIG / DATA

CONFIG_PATH = os.path.join(ROOT, "config.yaml")
AC_LABEL = {"equity": "Equities", "bond": "Bonds", "commodity": "Commodities", "currency": "Currencies"}


@st.cache_data(show_spinner=False)
def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@st.cache_data(show_spinner="Cargando retornos…")
def _load_returns(config_str: str):
    return load_returns(yaml.safe_load(config_str))


@st.cache_data(show_spinner="Corriendo backtest…")
def _run_backtest(config_str: str, signal_type: str, data_token: str = ""):
    # data_token (= último mes completo) entra en la cache key: el backtest se recalcula
    # cuando cierra un mes nuevo, no en cada update diario ni en reruns sueltos.
    config = yaml.safe_load(config_str)
    returns = load_returns(config)
    results = BacktestEngine(config).run(returns, use_signal_strength=(signal_type == "strength"))
    return results, returns


_OPT_CACHE = os.path.join(ROOT, "logs", "opt_cache.json")


def _opt_disk_cached(base_config_str: str, data_token: str):
    """Optimización con caché EN DISCO: persiste entre reinicios del dashboard. La
    grilla (lookback × target vol) tarda ~8s, pero solo depende de señal/ponderación
    y de los datos — así que se guarda en disco y solo se recalcula si esos cambian
    (no en cada reinicio). Clave = hash(config base + último mes completo)."""
    import hashlib
    import json
    key = hashlib.md5((base_config_str + "|" + str(data_token)).encode()).hexdigest()
    cache = {}
    if os.path.exists(_OPT_CACHE):
        try:
            cache = json.load(open(_OPT_CACHE))
        except Exception:
            cache = {}
    if key in cache:
        return cache[key]
    config = yaml.safe_load(base_config_str)
    returns = load_returns(config)
    best, _ = optimize_sharpe(returns, config)
    best = {"lookback": int(best["lookback"]), "target_vol": float(best["target_vol"]),
            "sharpe": float(best["sharpe"])}    # nativos para JSON
    cache[key] = best
    try:
        os.makedirs(os.path.dirname(_OPT_CACHE), exist_ok=True)
        json.dump(cache, open(_OPT_CACHE, "w"))
    except Exception:
        pass
    return best


@st.cache_data(show_spinner="Optimizando Sharpe (lookback × target vol)…")
def _optimal_params(base_config_str: str, data_token: str = ""):
    """(lookback, target_vol) que maximizan el Sharpe para la señal/ponderación dadas.
    data_token (= último mes completo) invalida la cache cuando cierra un mes nuevo.
    Caché en memoria (sesión) + en disco (entre reinicios)."""
    return _opt_disk_cached(base_config_str, data_token)


@st.cache_data(show_spinner="Actualizando datos de mercado (yfinance)…")
def _refresh_market_data(day_token: str, prices_path: str):
    """Baja precios nuevos de yfinance UNA VEZ por día (cache keyed por fecha).
    Incremental: solo agrega los días faltantes al parquet. Si falla la red,
    no rompe el dashboard — devuelve el estado y se sigue con los datos existentes."""
    from src.data.loader import update_prices
    from src.data.universe import _ALL_ETFS  # universo crudo completo (mantiene el parquet entero)
    try:
        df = update_prices(prices_path, tickers=list(_ALL_ETFS.keys()))
        return {"ok": True, "last": str(df.index[-1].date()), "rows": int(len(df))}
    except Exception as e:  # red caída, rate-limit, etc.
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ============================================================ HELPERS

def pct(x, d=2, signed=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    s = f"{x*100:+.{d}f}%" if signed else f"{x*100:.{d}f}%"
    return s


def num(x, d=2):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def usd(x, d=0):
    return f"${x:,.{d}f}"


def tone(x):
    return "pos" if x >= 0 else "neg"


def portfolio_vol(weights, returns_df):
    """Volatilidad anualizada estimada de un portafolio dados los pesos y la
    covarianza histórica (mensual) de los retornos. weights: Series ticker->peso."""
    common = [t for t in weights.index if t in returns_df.columns]
    if len(common) < 2:
        return float("nan")
    w = weights.reindex(common).fillna(0.0).values
    cov = returns_df[common].cov().values          # covarianza mensual
    var_m = float(w @ cov @ w)
    return (max(var_m, 0.0) * 12) ** 0.5           # anualizada


def kpi(label, value, delta="", value_cls="", delta_cls="tone-dim"):
    return (f'<div class="kpi"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value {value_cls}">{value}</div>'
            f'<div class="kpi-delta {delta_cls}">{delta}</div></div>')


def sparkline(values, color, width=250, height=54):
    vals = [float(v) for v in values if v is not None and not np.isnan(v)]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = " ".join(
        f"{i/(n-1)*(width-2)+1:.1f},{height-2-((v-lo)/rng)*(height-4):.1f}"
        for i, v in enumerate(vals)
    )
    return (f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
            f'style="display:block">'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.4" points="{pts}"/></svg>')


def topbar(asof, lookback, target_vol, signal_type, sharpe):
    return f"""
    <div class="topbar">
      <div class="tb-left">
        <span class="tb-brand">TSMOM<span>·TERMINAL</span></span>
        <span class="tb-sep">│</span><span class="tb-tag">F414 · UdeSA</span>
        <span class="tb-sep">│</span><span class="tb-muted">Time Series Momentum · {len(ETF_UNIVERSE)} ETFs</span>
      </div>
      <div class="tb-right">
        <span class="tb-chip"><span class="dot"></span>PAPER · IBKR 7497</span>
        <span class="tb-chip">LB <b>{lookback}m</b></span>
        <span class="tb-chip">TV <b>{target_vol*100:.0f}%</b></span>
        <span class="tb-chip">SHARPE <b>{sharpe:.2f}</b></span>
        <span class="tb-chip accent">{signal_type.upper()}</span>
        <span class="tb-sep">│</span><span class="tb-muted">corte {asof}</span>
      </div>
    </div>"""


def read_trades_csv(path):
    """Lee logs/trades.csv tolerando un archivo SIN fila de header (versiones viejas
    del logger lo escribían sin encabezado). Devuelve un DataFrame con columnas
    nombradas y 'timestamp' parseada, o None si está vacío."""
    from src.broker.orders import TRADE_HEADER
    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        df = pd.read_csv(path, header=None, names=TRADE_HEADER)
        df = df[df["timestamp"].astype(str) != "timestamp"]  # descarta header repetido si lo hubiera
    if df.empty:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df.dropna(subset=["timestamp"])


def calc_overlay(signal_type, weighting, window):
    return f"""
    <div class="calc-overlay">
      <div class="calc-card">
        <div class="calc-eyebrow">TSMOM · OPTIMIZACIÓN IN-SAMPLE</div>
        <div class="calc-title">Calculando parámetros óptimos</div>
        <div class="calc-sub">
          Buscando el <b>lookback</b> y el <b>target vol</b> que maximizan el Sharpe<br>
          sobre toda la historia de los ETFs <b>({window})</b><br>
          para señal <b>{signal_type.upper()}</b> · ponderación <b>{weighting.upper()}</b>
        </div>
        <div class="calc-bar"></div>
        <div class="calc-foot"><span class="dot"></span>barriendo grilla de parámetros…</div>
      </div>
    </div>"""


def data_overlay():
    return """
    <div class="calc-overlay">
      <div class="calc-card">
        <div class="calc-eyebrow">TSMOM · SINCRONIZACIÓN DE DATOS</div>
        <div class="calc-title">Actualizando datos de mercado</div>
        <div class="calc-sub">
          Descargando los precios más recientes de los ETFs<br>
          para correr el backtest con la información al día
        </div>
        <div class="calc-bar"></div>
        <div class="calc-foot"><span class="dot"></span>conectando con el proveedor de datos…</div>
      </div>
    </div>"""


def panel(title, body, sub="", right=""):
    sub_h = f'<span class="panel-sub">{sub}</span>' if sub else ""
    right_h = f'<div class="panel-sub">{right}</div>' if right else ""
    return (f'<div class="panel"><div class="panel-head">'
            f'<div class="panel-title">{title} {sub_h}</div>{right_h}</div>'
            f'<div class="panel-body">{body}</div></div>')


# ============================================================ APP SHELL

st.set_page_config(page_title="TSMOM Terminal · F414 UdeSA", page_icon="📟",
                   layout="wide", initial_sidebar_state="expanded")

if "theme" not in st.session_state:
    st.session_state.theme = "graphite"
st.markdown(T.inject(st.session_state.theme), unsafe_allow_html=True)
PAL = T.PALETTES[st.session_state.theme]

# Placeholder en el área principal para el overlay de cálculo del óptimo.
# Se crea antes del sidebar para que renderice sobre toda la pantalla; se llena
# justo antes de optimizar y se vacía al terminar (sólo se ve cuando el cálculo tarda).
opt_overlay = st.empty()

with st.sidebar:
    st.markdown(
        '<div class="side-head"><div class="side-logo">◢</div>'
        '<div><div class="side-title">TSMOM</div><div class="side-sub">SYSTEM v2.1</div></div></div>',
        unsafe_allow_html=True)

    page = st.radio("Navegación",
                    ["01 · Overview", "02 · Backtest", "03 · Robustness",
                     "04 · Live Portfolio", "05 · Trade Log", "06 · Rebalances"],
                    label_visibility="collapsed")

    st.markdown('<div class="side-label">Parámetros</div>', unsafe_allow_html=True)

    config = _load_config()

    # --- Actualización diaria de datos (se dispara al abrir el dashboard) ---
    # Refresca el parquet con los precios más recientes de yfinance, UNA vez por día.
    # Se pinta el overlay grande mientras descarga; Streamlit solo lo muestra si el
    # update realmente bloquea (cache fría/primer ingreso del día) y lo limpia al terminar.
    # Si la red falla, sigue con lo que ya hay.
    from datetime import date
    from src.data.loader import last_complete_month_end
    prices_path = os.path.join(ROOT, config["data"]["path"])
    opt_overlay.markdown(data_overlay(), unsafe_allow_html=True)
    data_refresh = _refresh_market_data(date.today().isoformat(), prices_path)  # 1x por día
    opt_overlay.empty()
    # Cache key del óptimo/backtest = ÚLTIMO MES COMPLETO (mes-granular). La estrategia
    # es mensual, así que los retornos solo cambian cuando cierra un mes nuevo: el óptimo
    # se recalcula SOLO entonces, NO en cada update diario ni en cada rerun (ej. apretar
    # "Test conexión" en Live Portfolio, que antes lo recalculaba por usar el mtime del parquet).
    data_token = last_complete_month_end()

    # Ventana abierta: fijamos end_date al último mes COMPLETO (auto-avanza mes a mes).
    # Concreto en el config en memoria => sirve para los displays y entra en la cache key.
    config["backtest"]["end_date"] = last_complete_month_end()

    # Señal y ponderación van primero: el óptimo de (lookback, target vol) depende de ellas.
    # 'multihorizon' (Baz et al. 2015) quedó FUERA de las opciones operables: su esquema está
    # pensado para tendencias rápidas con datos diarios y rinde peor en nuestro rebalanceo mensual
    # sobre ETF (ver justificación en dashboard_walkthrough.ipynb). El código sigue disponible en
    # src/strategy/signals.py por si se quisiera retomar.
    signal_type = st.radio("Señal", ["strength", "binary"], horizontal=True)
    weighting = st.radio("Ponderación", ["pooled", "class_balanced"], horizontal=True)

    # Óptimo in-sample (maximiza Sharpe) para la señal/ponderación elegidas.
    base_cfg = yaml.safe_load(yaml.dump(config))
    base_cfg["strategy"]["signal_mode"] = signal_type
    base_cfg["strategy"]["weighting"] = weighting
    # El overlay se pinta antes de optimizar; Streamlit sólo lo muestra mientras el
    # cálculo bloquea (cache frío / reinicio) y lo limpia apenas termina.
    opt_window = f'{config["backtest"]["start_date"][:4]}–{config["backtest"]["end_date"][:4]}'
    opt_overlay.markdown(calc_overlay(signal_type, weighting, opt_window), unsafe_allow_html=True)
    opt = _optimal_params(yaml.dump(base_cfg), data_token)
    opt_overlay.empty()

    # Default = óptimo. Se fija al óptimo al abrir el dashboard y cada vez que cambia
    # señal/ponderación; entre medio el usuario puede mover los sliders libremente.
    combo = f"{signal_type}|{weighting}"
    if st.session_state.get("_opt_combo") != combo:
        st.session_state["_opt_combo"] = combo
        st.session_state["lookback"] = opt["lookback"]
        st.session_state["target_vol"] = opt["target_vol"]

    lookback = st.slider("Lookback (meses)", 3, 24, step=1, key="lookback")
    target_vol = st.slider("Target Vol (anual)", 0.05, 0.40, step=0.01, key="target_vol")

    at_opt = (lookback == opt["lookback"] and abs(target_vol - opt["target_vol"]) < 0.005)
    st.caption(
        f"{'★ ' if at_opt else ''}Óptimo Sharpe **{opt['sharpe']:.2f}** · "
        f"LB {opt['lookback']}m · TV {opt['target_vol']*100:.0f}%"
        + ("" if at_opt else " · _moviste los parámetros fuera del óptimo_")
    )
    def _reset_to_opt(lb=opt["lookback"], tv=opt["target_vol"]):
        # Callback: corre antes del rerun, por eso sí puede modificar el estado
        # de widgets ya instanciados (lookback / target_vol).
        st.session_state["lookback"] = lb
        st.session_state["target_vol"] = tv

    if not at_opt:
        st.button("↺ Volver al óptimo", use_container_width=True, on_click=_reset_to_opt)

    config["strategy"]["lookback_months"] = lookback
    config["strategy"]["target_volatility"] = target_vol
    config["strategy"]["signal_mode"] = signal_type
    config["strategy"]["weighting"] = weighting
    config_str = yaml.dump(config)

    win = f'{config["backtest"]["start_date"][:7]} → {config["backtest"]["end_date"][:7]}'
    if data_refresh.get("ok"):
        datos_html = f'<b class="tone-accent">↻ {data_refresh["last"]}</b>'
    else:
        datos_html = '<b class="tone-neg">sin conexión</b>'
    st.markdown(
        f'<div class="side-foot">'
        f'<div class="foot-row"><span>UNIVERSO</span><b>{len(ETF_UNIVERSE)} ETF</b></div>'
        f'<div class="foot-row"><span>REBAL</span><b>MENSUAL</b></div>'
        f'<div class="foot-row"><span>VENTANA</span><b>{win}</b></div>'
        f'<div class="foot-row"><span>DATOS</span>{datos_html}</div>'
        f'<div class="foot-row"><span>CAPITAL</span><b>$1.00M</b></div></div>',
        unsafe_allow_html=True)

# Datos compartidos
results, returns = _run_backtest(config_str, signal_type, data_token)
r = results.portfolio_returns
equity = (1 + r).cumprod()
sharpe = sharpe_ratio(r)
asof = returns.index[-1].strftime("%Y-%m")
period_label = f"{returns.index[0].year}–{returns.index[-1].year}"

st.markdown(topbar(asof, lookback, target_vol, signal_type, sharpe), unsafe_allow_html=True)


# ============================================================ PÁGINA 1 · OVERVIEW

if page.startswith("01"):
    st.markdown('<div class="page-h1">Time Series Momentum <span class="dim">— Overview</span></div>'
                f'<div class="page-sub">Señales del próximo rebalanceo · corte {asof} · lookback {lookback}m</div>',
                unsafe_allow_html=True)

    strength = compute_signal_strength(returns, lookback=lookback)
    sig_bin = compute_tsmom_signal(returns, lookback=lookback)
    last_str = strength.iloc[-1]
    last_dir = sig_bin.iloc[-1]
    valid = last_dir.dropna()
    n_long = int((valid == 1).sum())
    n_short = int((valid == -1).sum())
    net_exp = (n_long - n_short) / max(len(valid), 1)
    since = equity.iloc[-1] - 1

    strip = "".join([
        kpi("Universo", f"{len(ETF_UNIVERSE)}", "ETFs · 4 clases"),
        kpi("Sharpe (IS)", f"{sharpe:.2f}", period_label, "accent", "tone-accent"),
        kpi("Ret. desde inicio", pct(since, 1, True), "neto de costos", "", f"tone-{tone(since)}"),
        kpi("Net exposure", pct(net_exp, 0, True), f"{n_long}L · {n_short}S", "", f"tone-{tone(net_exp)}"),
        kpi("Posiciones", f"{n_long + n_short}", "todas activas"),
    ])
    st.markdown(f'<div class="kpi-strip">{strip}</div>', unsafe_allow_html=True)

    col_main, col_side = st.columns([2.1, 1])

    with col_main:
        sections = ""
        for ac in ASSET_CLASSES:
            tickers = [t for t in valid.index if ETF_UNIVERSE.get(t) == ac]
            if not tickers:
                continue
            cells = ""
            for tk in sorted(tickers):
                d = last_dir.get(tk, 0)
                s = last_str.get(tk, 0.0)
                s = 0.0 if pd.isna(s) else float(s)
                intn = min(1.0, abs(s) / 3.0)
                side = "sig-pos" if d >= 0 else "sig-neg"
                name, desc = ETF_INFO.get(tk, (tk, AC_LABEL.get(ETF_UNIVERSE.get(tk, ""), "—")))
                dir_lbl = "LONG" if d >= 0 else "SHORT"
                dir_cls = "tone-pos" if d >= 0 else "tone-neg"
                cells += (f'<details class="sigcell {side}" style="--int:{intn:.2f}">'
                          f'<summary>'
                          f'<span class="sig-tk">{tk}</span>'
                          f'<span class="sig-bar"><span style="width:{intn*100:.0f}%"></span></span>'
                          f'</summary>'
                          f'<div class="sig-pop">'
                          f'<div class="sig-pop-name">{html.escape(name)}</div>'
                          f'<div class="sig-pop-desc">{html.escape(desc)}</div>'
                          f'<div class="sig-pop-metrics">'
                          f'<span>Dirección<b class="{dir_cls}">{dir_lbl}</b></span>'
                          f'<span>Fuerza<b>{s:+.2f}</b></span>'
                          f'<span>Intensidad<b>{intn*100:.0f}%</b></span>'
                          f'</div></div></details>')
            nl = sum(1 for t in tickers if last_dir.get(t, 0) >= 0)
            sections += (f'<div class="sig-class"><div class="sig-class-head">'
                         f'<span class="sig-class-name">{AC_LABEL[ac]}</span>'
                         f'<span class="sig-class-meta">{len(tickers)} · {nl}L/{len(tickers)-nl}S</span></div>'
                         f'<div class="sig-grid">{cells}</div></div>')
        st.markdown(panel("SEÑAL TSMOM — MATRIZ DE ACTIVOS", sections,
                          sub="intensidad = |fuerza de tendencia|"), unsafe_allow_html=True)

    with col_side:
        spark = sparkline(equity.values, PAL["accent"])
        nav_body = (f'<div class="nav-val">{equity.iloc[-1]:.3f}×</div>'
                    f'<div class="nav-delta tone-{tone(since)}">{pct(since,1,True)}</div>'
                    f'{spark}'
                    f'<div class="nav-foot"><span>vol <b>{pct(annualized_volatility(r),1)}</b></span>'
                    f'<span>maxDD <b class="tone-neg">{pct(max_drawdown(r),1)}</b></span>'
                    f'<span>calmar <b>{num(calmar_ratio(r))}</b></span></div>')
        st.markdown(panel("NAV DESDE INICIO", nav_body, sub="base 1.00×"), unsafe_allow_html=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'EXPOSICIÓN POR CLASE <span class="panel-sub">long vs short</span></div></div>'
                    '<div class="panel-body">', unsafe_allow_html=True)
        for ac in ASSET_CLASSES:
            tickers = [t for t in valid.index if ETF_UNIVERSE.get(t) == ac]
            if not tickers:
                continue
            nl = sum(1 for t in tickers if last_dir.get(t, 0) >= 0)
            ns = len(tickers) - nl
            st.markdown(f'<div class="ac-pie-head"><span class="ac-pie-name">{AC_LABEL[ac]}</span>'
                        f'<span class="ac-pie-meta">{nl}L · {ns}S</span></div>', unsafe_allow_html=True)
            fpie = go.Figure(go.Pie(
                labels=["Long", "Short"], values=[nl, ns], sort=False, direction="clockwise",
                hole=0.62, marker=dict(colors=[PAL["pos"], PAL["neg"]],
                                       line=dict(color=PAL["bg-1"], width=2)),
                textinfo="value", textfont=dict(family=T.MONO, size=13, color=PAL["bg-1"]),
                hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"))
            fpie.update_layout(
                paper_bgcolor=PAL["bg-1"], plot_bgcolor=PAL["bg-1"], height=132,
                margin=dict(l=8, r=8, t=4, b=4), showlegend=False,
                annotations=[dict(text=f"{nl+ns}", x=0.5, y=0.5, showarrow=False,
                                  font=dict(family=T.MONO, size=17, color=PAL["text"]))])
            st.plotly_chart(fpie, use_container_width=True,
                            config={"displayModeBar": False}, key=f"acpie_{ac}")
        st.markdown(f'<div class="ac-foot">Net exposure agregado '
                    f'<b class="{tone(net_exp)}">{pct(net_exp,0,True)}</b> · gross 100% · '
                    f'{n_long} long / {n_short} short</div>'
                    '</div></div>', unsafe_allow_html=True)


# ============================================================ PÁGINA 2 · BACKTEST

elif page.startswith("02"):
    st.markdown('<div class="page-h1">Backtest <span class="dim">— Resultados</span></div>'
                f'<div class="page-sub">{config["backtest"]["start_date"][:7]} → {config["backtest"]["end_date"][:7]} · '
                f'{len(r)} meses · costos {config["transaction_costs"]["bid_ask_spread"]*1e4:.0f}bps spread + '
                f'{config["transaction_costs"]["commission_pct"]*1e4:.0f}bps comisión</div>',
                unsafe_allow_html=True)

    strip = "".join([
        kpi("Sharpe Ratio", f"{sharpe:.2f}", "rf = 0", "accent", "tone-accent"),
        kpi("Ann. Return", pct(annualized_return(r), 1), "neto", "", "tone-pos"),
        kpi("Ann. Volatility", pct(annualized_volatility(r), 1), f"target {target_vol*100:.0f}%"),
        kpi("Max Drawdown", pct(max_drawdown(r), 1), "peak-to-trough", "", "tone-neg"),
        kpi("Calmar Ratio", num(calmar_ratio(r)), "ret/maxDD", "accent", "tone-accent"),
    ])
    st.markdown(f'<div class="kpi-strip">{strip}</div>', unsafe_allow_html=True)

    cum_net = equity
    cum_gross = (1 + results.gross_returns).cumprod()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cum_gross.index, y=cum_gross.values, name="Bruto",
                             line=dict(color=PAL["text-mute"], width=1.3, dash="dot")))
    fig.add_trace(go.Scatter(x=cum_net.index, y=cum_net.values, name="Neto",
                             line=dict(color=PAL["accent"], width=2),
                             fill="tozeroy", fillcolor=T.rgba(PAL["accent"], 0.08)))
    fig.update_yaxes(type="log")
    T.fig_layout(fig, PAL, height=300, legend=True)
    st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">CURVA DE CAPITAL '
                '<span class="panel-sub">escala log · neto vs bruto</span></div></div>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([1.4, 1])
    with c1:
        dd = (cum_net - cum_net.cummax()) / cum_net.cummax()
        fdd = go.Figure()
        fdd.add_trace(go.Scatter(x=dd.index, y=dd.values * 100, fill="tozeroy",
                                 fillcolor=T.rgba(PAL["neg"], 0.15), line=dict(color=PAL["neg"], width=1.3),
                                 name="Drawdown"))
        T.fig_layout(fdd, PAL, height=230)
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">DRAWDOWN '
                    '<span class="panel-sub">underwater %</span></div></div>', unsafe_allow_html=True)
        st.plotly_chart(fdd, use_container_width=True, config={"displayModeBar": False})
        st.markdown('</div>', unsafe_allow_html=True)
    with c2:
        rows = [
            ("Annualized Return", pct(annualized_return(r), 2), "mrow-v tone-pos"),
            ("Annualized Volatility", pct(annualized_volatility(r), 2), "mrow-v"),
            ("Sharpe Ratio", num(sharpe), "mrow-v tone-accent"),
            ("Sortino Ratio", num(sortino_ratio(r)), "mrow-v tone-accent"),
            ("Max Drawdown", pct(max_drawdown(r), 2), "mrow-v tone-neg"),
            ("Calmar Ratio", num(calmar_ratio(r)), "mrow-v"),
            ("Hit Rate", pct(hit_rate(r), 1), "mrow-v"),
            ("Avg Monthly Turnover", pct(turnover(results.weights), 1), "mrow-v"),
            ("Num Months", str(len(r)), "mrow-v"),
        ]
        body = "".join(f'<div class="mrow"><span class="mrow-k">{k}</span>'
                       f'<span class="{cls}">{v}</span></div>' for k, v, cls in rows)
        st.markdown(panel("MÉTRICAS DE PERFORMANCE", f'<div class="mtable">{body}</div>'),
                    unsafe_allow_html=True)

    monthly_df = pd.DataFrame({"year": r.index.year, "month": r.index.month, "ret": r.values})
    pivot = monthly_df.pivot(index="year", columns="month", values="ret")
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    fh = go.Figure(go.Heatmap(
        z=pivot.values * 100, x=list(pivot.columns), y=[str(y) for y in pivot.index],
        colorscale=[[0, PAL["neg"]], [0.5, PAL["bg-1"]], [1, PAL["accent"]]], zmid=0,
        text=np.round(pivot.values * 100, 1), texttemplate="%{text}",
        textfont=dict(size=9, family="JetBrains Mono"), showscale=False,
        hovertemplate="%{y} %{x}: %{z:.1f}%<extra></extra>"))
    fh.update_yaxes(autorange="reversed")
    T.fig_layout(fh, PAL, height=300)
    st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">RETORNOS MENSUALES '
                '<span class="panel-sub">% · verde = ganancia</span></div></div>', unsafe_allow_html=True)
    st.plotly_chart(fh, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)


# ============================================================ PÁGINA 3 · ROBUSTNESS

elif page.startswith("03"):
    st.markdown('<div class="page-h1">Tests de Robustez</div>'
                '<div class="page-sub">sensibilidad paramétrica · performance en crisis · validación out-of-sample</div>',
                unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["SENSIBILIDAD", "STRESS TEST", "OUT-OF-SAMPLE"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            lb_df = lookback_sensitivity(returns, config)
            flb = go.Figure(go.Bar(x=[str(i) for i in lb_df.index], y=lb_df["sharpe"],
                                   marker_color=[PAL["accent"] if v >= 0 else PAL["neg"] for v in lb_df["sharpe"]]))
            T.fig_layout(flb, PAL, height=250)
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">SHARPE POR LOOKBACK '
                        '<span class="panel-sub">meses</span></div></div>', unsafe_allow_html=True)
            st.plotly_chart(flb, use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)
        with c2:
            cs_df = cost_sensitivity(returns, config).reset_index()
            xcol = cs_df.columns[0]
            fcs = go.Figure(go.Scatter(x=cs_df[xcol], y=cs_df["sharpe"], mode="lines+markers",
                                       line=dict(color=PAL["accent"], width=2),
                                       marker=dict(color=PAL["accent"], size=7)))
            T.fig_layout(fcs, PAL, height=250)
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">SHARPE vs COSTOS '
                        '<span class="panel-sub">spread bid-ask</span></div></div>', unsafe_allow_html=True)
            st.plotly_chart(fcs, use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'SENSIBILIDAD AL TARGET VOL</div></div>', unsafe_allow_html=True)
        tv_df = target_vol_sensitivity(returns, config)
        st.dataframe(tv_df.round(3), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        cum = equity
        fc = go.Figure()
        fc.add_trace(go.Scatter(x=cum.index, y=cum.values, name="Portfolio",
                                line=dict(color=PAL["accent"], width=2)))
        for name, (s, e) in CRISIS_PERIODS.items():
            fc.add_vrect(x0=s, x1=e, fillcolor=PAL["neg"], opacity=0.10, line_width=0,
                         annotation_text=name, annotation_position="top left",
                         annotation_font=dict(size=9, color=PAL["text-dim"]))
        fc.update_yaxes(type="log")
        T.fig_layout(fc, PAL, height=300)
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'EQUITY CURVE — CRISIS SOMBREADAS <span class="panel-sub">escala log</span></div></div>',
                    unsafe_allow_html=True)
        st.plotly_chart(fc, use_container_width=True, config={"displayModeBar": False})
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'PERFORMANCE DURANTE CRISIS</div></div>', unsafe_allow_html=True)
        st.dataframe(analyze_crisis_performance(r), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        wf_df = walk_forward(returns, config)
        if not wf_df.empty:
            fw = go.Figure(go.Bar(x=wf_df["test_start"].astype(str), y=wf_df["sharpe"],
                                  marker_color=[PAL["accent"] if v >= 0 else PAL["neg"] for v in wf_df["sharpe"]]))
            fw.add_hline(y=0, line_dash="dash", line_color=PAL["border"])
            T.fig_layout(fw, PAL, height=260)
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                        'WALK-FORWARD — SHARPE OUT-OF-SAMPLE</div></div>', unsafe_allow_html=True)
            st.plotly_chart(fw, use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)
            st.dataframe(wf_df.round(2), use_container_width=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'IN-SAMPLE vs OUT-OF-SAMPLE</div></div>', unsafe_allow_html=True)
        st.dataframe(expanding_window(returns, config).round(2), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)


# ============================================================ PÁGINA 4 · LIVE PORTFOLIO

elif page.startswith("04"):
    import time as _time
    from datetime import datetime as _dt
    from src.broker import state as _state
    from src.broker.session import ibkr_session
    from src.broker.runner import check_rebalance, compute_target_weights

    st.markdown('<div class="page-h1">Live Portfolio <span class="dim">— IBKR Paper Trading</span></div>'
                '<div class="page-sub">conectá tu cuenta · poné la estrategia a correr · '
                'cerrá y reconectá cuando quieras — IBKR mantiene tus posiciones</div>',
                unsafe_allow_html=True)

    # ====================================================== HORARIO DE MERCADO (US)
    from src.broker.market_hours import us_market_status
    mk = us_market_status()
    trade_note = ("market orders confiables" if mk["can_trade"]
                  else "market orders POCO confiables — esperá la sesión regular")
    mk_body = (
        f'<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">'
        f'<span style="font-size:1.15rem;font-weight:700;color:{mk["color"]}">{mk["label"]}</span>'
        f'<span class="panel-sub">{mk["detail"]}</span></div>'
        f'<div class="mtable" style="margin-top:8px">'
        f'<div class="mrow"><span class="mrow-k">Ahora</span>'
        f'<span class="mrow-v">{mk["now_et"]}  ·  {mk["now_local"]} (tu hora)</span></div>'
        f'<div class="mrow"><span class="mrow-k">Sesión regular</span>'
        f'<span class="mrow-v">{mk["regular_et"]}  ·  {mk["regular_local"]}</span></div>'
        f'<div class="mrow"><span class="mrow-k">Horario extendido</span>'
        f'<span class="mrow-v">{mk["extended_et"]}  ·  {mk["extended_local"]}</span></div>'
        f'<div class="mrow"><span class="mrow-k">Operatoria ahora</span>'
        f'<span class="mrow-v" style="color:{mk["color"]}">{trade_note}</span></div>'
        + ('' if mk["can_trade"] else
           f'<div class="mrow"><span class="mrow-k">Próxima sesión regular</span>'
           f'<span class="mrow-v">{mk["next_open_local"]} (tu hora)</span></div>')
        + '</div>')
    st.markdown(panel("HORARIO DE MERCADO — ETFs US", mk_body,
                      sub="NYSE/NASDAQ · no contempla feriados"), unsafe_allow_html=True)
    if not mk["can_trade"]:
        st.caption("⚠️ Fuera de la sesión regular las órdenes a mercado pueden no ejecutarse "
                   "(sin liquidez / preset TIF). Para operar en firme, hacelo en sesión regular.")

    STATUS_UI = {
        "running": ("● ACTIVA", "var(--accent)"),
        "paused":  ("⏸ PAUSADA", "#e0a23b"),
        "stopped": ("○ DETENIDA", "var(--text-dim)"),
    }

    # Target weights del próximo rebalanceo (no requiere IBKR).
    target_weights = compute_target_weights(returns, config)
    reb_params = {"signal_mode": signal_type, "lookback": lookback, "target_vol": target_vol}

    def _deploy_capital(net_liq: float) -> float:
        """Capital que maneja la estrategia: SOLO su propia plata, no el portafolio.

        Base = «Capital a destinar» (lo que el usuario asignó) + las ganancias/pérdidas
        acumuladas de la estrategia → así reinvierte SUS ganancias (compounding) pero
        nunca usa más dinero que el asignado para ella. Cota dura: el NetLiquidation real
        de la cuenta (jamás despliega más de lo que hay)."""
        chosen = st.session_state.get("capital_deploy")
        if not chosen or chosen <= 0:
            chosen = net_liq
        cum_pnl = float((st.session_state.get("live") or {}).get("cum_pnl", 0.0))
        equity = float(chosen) + cum_pnl          # asignado + ganancias propias
        return float(min(max(equity, 1_000.0), net_liq))

    def _fetch_live(execute_due=False):
        """Conecta, trae portafolio/cuenta/PnL e info de conexión. Si execute_due y
        la estrategia está ACTIVA con un rebalanceo pendiente, lo ejecuta (auto-trade)."""
        from src.broker.monitor import get_live_portfolio, compute_live_pnl
        from src.broker.orders import execute_rebalance
        from src.broker.market_hours import us_market_status
        auto_msg = None
        # Auto-trade solo en sesión regular: fuera de horario las órdenes no llenan bien.
        market_open = us_market_status()["can_trade"]
        with ibkr_session(config, "monitor") as conn:
            info = conn.get_connection_info()
            if execute_due and market_open and _state.is_running() and _state.rebalance_due():
                capital = _deploy_capital(conn.get_account_summary().get("NetLiquidation", 1_000_000))
                res = execute_rebalance(conn, target_weights, capital=capital,
                                        dry_run=False, trigger="auto", params=reb_params)
                auto_msg = (f"Auto-trade: {res['n_filled']}/{len(res['orders'])} órdenes "
                            f"llenadas con {usd(capital)}"
                            + (f" · {len(res['skipped'])} omitidas (< 1 acción)" if res["skipped"] else ""))
            portfolio_df = get_live_portfolio(conn)
            account = conn.get_account_summary()
            pnl = compute_live_pnl(portfolio_df)
        # P&L ACUMULADO real de la estrategia (realizado + no realizado):
        #   = valor de mercado (con signo) de las posiciones − net_deployed
        # Continuo entre rebalanceos. La primera vez (net_deployed=0 con posiciones
        # pre-existentes) se inicializa desde el costo base para no contar el capital
        # como ganancia.
        _sdf = (portfolio_df[portfolio_df["ticker"].isin(ETF_UNIVERSE)]
                if not portfolio_df.empty else portfolio_df)
        invested = float(_sdf["market_value"].abs().sum()) if not _sdf.empty else 0.0
        signed_mv = float(_sdf["market_value"].sum()) if not _sdf.empty else 0.0
        net_dep = float(_state.get_state().get("net_deployed", 0.0))
        if net_dep == 0.0 and not _sdf.empty:
            net_dep = float((_sdf["qty"] * _sdf["avg_cost"]).sum())   # init costo base
            _state.set_net_deployed(net_dep)
        cum_pnl = signed_mv - net_dep
        # Drift total actual (fracción del portafolio a reasignar para volver al target).
        _tgt_pct = target_weights / (float(target_weights.abs().sum()) or 1.0)
        _curw = ((_sdf.groupby("ticker")["market_value"].sum() / invested)
                 if (not _sdf.empty and invested) else pd.Series(dtype=float))
        drift_total = float(sum(abs(float(_tgt_pct.get(k, 0.0)) - float(_curw.get(k, 0.0)))
                                for k in _tgt_pct.index.union(_curw.index))) / 2
        st.session_state["live"] = {"account": account, "portfolio": portfolio_df,
                                    "pnl": pnl, "info": info, "invested": invested,
                                    "cum_pnl": cum_pnl, "drift_total": drift_total,
                                    "ts": _time.strftime("%H:%M:%S")}
        # Foto del rendimiento ACUMULADO + drift para el gráfico (persiste entre sesiones).
        if invested > 0:
            try:
                from src.broker.orders import log_nav_snapshot
                log_nav_snapshot(invested, cum_pnl, drift_total)
            except Exception:
                pass
        if auto_msg:
            st.session_state["auto_msg"] = auto_msg

    def _test_connection():
        with ibkr_session(config, "status") as conn:
            st.session_state["conn_info"] = {**conn.get_connection_info(),
                                             "ts": _time.strftime("%H:%M:%S")}

    # ====================================================== PANEL DE CONEXIÓN
    cc1, cc2, cc3 = st.columns([1, 1, 1])
    test_now = cc1.button("🔌 Test conexión")
    auto_refresh = cc2.toggle("Auto-refresh", value=False)
    interval_secs = cc3.number_input("Intervalo (seg)", 10, 300, 30, 10, disabled=not auto_refresh)

    if test_now:
        try:
            _test_connection()
        except Exception as e:
            st.session_state["conn_info"] = None
            st.error(f"No se pudo conectar a IBKR TWS: {e}")
            st.info("Verificá que TWS esté abierto y la API habilitada en puerto 7497.")

    info = st.session_state.get("conn_info") or (st.session_state.get("live") or {}).get("info")
    broker = config["broker"]
    if info and info.get("connected"):
        # Resumen de validación de operabilidad (de logs/ibkr_validation.csv si existe).
        val_path = os.path.join(ROOT, "logs", "ibkr_validation.csv")
        val_txt = ""
        if os.path.exists(val_path) and os.path.getsize(val_path) > 1:
            vdf = pd.read_csv(val_path)
            val_txt = f" · {int(vdf['tradeable'].sum())}/{len(vdf)} ETFs operables"
        conn_body = (
            f'<div class="mtable">'
            f'<div class="mrow"><span class="mrow-k">Estado</span>'
            f'<span class="mrow-v tone-accent">● CONECTADO</span></div>'
            f'<div class="mrow"><span class="mrow-k">Endpoint</span>'
            f'<span class="mrow-v">{info["host"]}:{info["port"]}</span></div>'
            f'<div class="mrow"><span class="mrow-k">Cuenta</span>'
            f'<span class="mrow-v">{info["account"]}</span></div>'
            f'<div class="mrow"><span class="mrow-k">Servidor IBKR</span>'
            f'<span class="mrow-v">v{info.get("server_version","?")}{val_txt}</span></div>'
            f'</div>')
        st.markdown(panel("CONEXIÓN BROKER — IBKR", conn_body,
                          sub=f"último check {info.get('ts','—')}"), unsafe_allow_html=True)
    else:
        st.markdown(panel("CONEXIÓN BROKER — IBKR",
                          '<div class="mtable">'
                          '<div class="mrow"><span class="mrow-k">Estado</span><span class="mrow-v tone-neg">○ DESCONECTADO</span></div>'
                          '<div class="mrow"><span class="mrow-k">1 · TWS → Edit → Global Configuration → API → Settings</span><span></span></div>'
                          '<div class="mrow"><span class="mrow-k">2 · ✅ Enable ActiveX and Socket Clients</span><span></span></div>'
                          f'<div class="mrow"><span class="mrow-k">3 · Puerto</span><span class="mrow-v">{broker["port"]} (7497 paper · 7496 real)</span></div>'
                          '<div class="mrow"><span class="mrow-k">4 · Agregar 127.0.0.1 en Trusted IPs</span><span></span></div>'
                          '<div class="mrow"><span class="mrow-k">5 · Clic en «Test conexión» arriba</span><span></span></div>'
                          '</div>', sub=f"{broker['host']}:{broker['port']}"), unsafe_allow_html=True)

    # ====================================================== CAPITAL A DESTINAR
    def _miles(x):
        """Formato con punto de miles (es-AR): 100000 -> '100.000'."""
        return f"{int(round(float(x))):,}".replace(",", ".")

    _net_liq = (st.session_state.get("live") or {}).get("account", {}).get("NetLiquidation")
    # Tope: el NetLiquidation real si está conectado; si no, el capital del config.
    _cap_max = max(int(_net_liq) if _net_liq else int(config["backtest"]["initial_capital"]), 2_000)
    _init_cap = int(float(st.session_state.get("capital_deploy")
                          or (_net_liq if _net_liq else config["backtest"]["initial_capital"])))

    # 'capital_deploy' es el valor CANÓNICO (lo lee _deploy_capital). 'cap_input' y
    # 'cap_slider' son los dos widgets enlazados: cualquiera actualiza al canónico
    # y sincroniza al otro (campo con Enter + slider, siempre en el mismo número).
    st.session_state.setdefault("capital_deploy", _init_cap)
    st.session_state.setdefault("cap_input", st.session_state.capital_deploy)
    st.session_state.setdefault("cap_slider", st.session_state.capital_deploy)
    for _k in ("capital_deploy", "cap_input", "cap_slider"):   # acotar al rango actual
        st.session_state[_k] = min(max(int(st.session_state[_k]), 1_000), _cap_max)

    def _cap_from_input():
        st.session_state.capital_deploy = int(st.session_state.cap_input)
        st.session_state.cap_slider = int(st.session_state.cap_input)

    def _cap_from_slider():
        st.session_state.capital_deploy = int(st.session_state.cap_slider)
        st.session_state.cap_input = int(st.session_state.cap_slider)

    st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                'CAPITAL A DESTINAR <span class="panel-sub">cuánto desplegar en esta '
                'operación</span></div></div>', unsafe_allow_html=True)
    cap_c1, cap_c2 = st.columns([1, 1.25])
    # Campo para escribir el monto (se aplica con Enter)…
    cap_c1.number_input(
        "Monto en USD (escribí y Enter)", min_value=1_000, max_value=_cap_max,
        step=1_000, format="%d", key="cap_input", on_change=_cap_from_input,
        help="Cuánta plata querés que la estrategia despliegue. Nunca opera por encima "
             "de este monto ni del NetLiquidation real de la cuenta.")
    # …o ajustar con el slider (se actualiza al instante, sin Enter).
    cap_c1.slider(
        "…o ajustá con el slider", min_value=1_000, max_value=_cap_max,
        step=1_000, format="$%d", key="cap_slider", on_change=_cap_from_slider)
    capital_deploy = int(st.session_state.capital_deploy)
    if _net_liq:
        _pctnl = capital_deploy / _net_liq * 100
        sub = (f'{_pctnl:.0f}% de <b>$ {_miles(_net_liq)}</b> disponibles · '
               f'el resto queda en cash')
    else:
        sub = 'conectá / actualizá el portafolio para acotarlo al NetLiquidation real'
    cap_c2.markdown(
        f'<div style="padding:2px 0 0 4px">'
        f'<div class="panel-sub" style="margin-bottom:2px">Vas a desplegar</div>'
        f'<div style="font-family:\'JetBrains Mono\',\'IBM Plex Mono\',monospace;'
        f'font-size:2.4rem;font-weight:700;color:var(--accent);line-height:1.05;'
        f'letter-spacing:.5px">$ {_miles(capital_deploy)}</div>'
        f'<div class="panel-sub" style="margin-top:4px">{sub}</div></div>',
        unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ====================================================== ESTRATEGIA (estado)
    auto_trade = st.toggle("⚡ Auto-trade — ejecutar el rebalanceo mensual solo (respeta pausa/kill)",
                           value=False,
                           help="Si está activo y la estrategia está ACTIVA, cuando empieza un mes "
                                "nuevo el dashboard ejecuta el rebalanceo automáticamente al actualizar. "
                                "Si está apagado, te avisa y vos confirmás.")

    strat = _state.get_state()
    chk = check_rebalance()
    label, color = STATUS_UI.get(strat["status"], STATUS_UI["stopped"])

    if strat["status"] == "stopped":
        st.markdown(
            f'<div class="panel"><div class="panel-body">'
            f'<b style="color:{color}">{label}</b> — la estrategia no está enrolada. '
            f'Iniciála para empezar a gestionar el portafolio con TSMOM.</div></div>',
            unsafe_allow_html=True)
        if st.button("▶ Iniciar estrategia", type="primary"):
            _state.start_strategy(reb_params)
            st.rerun()
    else:
        enrolled = strat.get("enrolled_at", "—")
        p = strat.get("params", {})
        pstr = (f'{str(p.get("signal_mode","?")).upper()} · LB{p.get("lookback","?")} · '
                f'TV{int(float(p.get("target_vol",0))*100)}%' if p else "—")
        last_rb = strat.get("last_rebalance_at")
        last_txt = last_rb if last_rb else "todavía sin operar"
        st.markdown(
            f'<div class="panel" style="border-color:{color}"><div class="panel-body">'
            f'<b style="color:{color}">{label}</b> desde <b>{enrolled}</b> · {pstr} · '
            f'<span class="mrow-k">última ejecución:</span> {last_txt}</div></div>',
            unsafe_allow_html=True)

        sc1, sc2 = st.columns(2)
        if strat["status"] == "running" and sc1.button("⏸ Pausar estrategia", use_container_width=True):
            _state.pause("pausa manual (dashboard)")
            st.rerun()
        if strat["status"] == "paused" and sc1.button("▶ Reanudar estrategia", type="primary",
                                                       use_container_width=True):
            _state.resume()
            st.rerun()
        refresh_now = sc2.button("🔄 Actualizar portafolio", use_container_width=True)

        # Traer el portafolio en vivo (auto-trade solo en un refresh real, manual o
        # auto-refresh; "Test conexión" nunca opera, solo monitorea).
        try:
            if refresh_now or auto_refresh:
                _fetch_live(execute_due=auto_trade)
            elif test_now and info:
                _fetch_live(execute_due=False)
        except Exception as e:
            st.error(f"Error al traer el portafolio de IBKR: {e}")
        _am = st.session_state.pop("auto_msg", None)
        if _am:
            st.success("⚡ " + _am)

        live = st.session_state.get("live")

        # ===================== BLOQUE 1 · EJECUTAR ESTRATEGIA =====================
        # Frame claro según el momento (sin jerga de "rebalanceo pendiente"):
        if last_rb is None:                       # nunca operó -> allocación inicial
            exec_sub, exec_btn = "allocación inicial", "▶ Ejecutar estrategia"
            exec_note = ("La estrategia está activa pero <b>todavía no operó</b>. Al ejecutar, "
                         "compra las posiciones objetivo del modelo TSMOM con el capital de arriba.")
        elif chk.due:                             # mes nuevo -> rebalanceo del mes
            exec_sub, exec_btn = "rebalanceo del mes", "▶ Ejecutar rebalanceo del mes"
            exec_note = ("Empezó un mes nuevo: ejecutá para <b>ajustar las posiciones</b> al "
                         "target TSMOM actualizado de este mes.")
        else:                                     # ya operó este mes
            exec_sub, exec_btn = f"al día · próxima {chk.next_rebalance_date}", "⟳ Rebalanceo instantáneo"
            exec_note = (f"✓ Ya se ejecutó este mes (última: <b>{last_rb}</b>). La próxima "
                         f"ejecución programada es el <b>{chk.next_rebalance_date}</b>. El "
                         f"<b>rebalanceo instantáneo</b> re-alinea las posiciones al target ahora "
                         f"(ajusta las diferencias; no agrega capital extra).")

        st.markdown(
            f'<div class="panel"><div class="panel-head"><div class="panel-title">'
            f'▶ EJECUTAR ESTRATEGIA <span class="panel-sub">{len(target_weights)} posiciones '
            f'objetivo · {exec_sub}</span></div></div>'
            f'<div class="panel-body">{exec_note}</div>', unsafe_allow_html=True)
        ec1, ec2 = st.columns(2)
        if ec1.button("🔍 Ver órdenes"):
            from src.broker.orders import execute_rebalance
            cap = _deploy_capital((st.session_state.get("live") or {}).get("account", {}).get("NetLiquidation", 1_000_000))
            st.session_state["dry_run_res"] = execute_rebalance(
                None, target_weights, capital=cap, dry_run=True)
        if _state.is_paused():
            st.warning("⏸ Estrategia pausada: reanudala (arriba) para poder ejecutar.")
        elif not mk["can_trade"]:
            # Mercado cerrado / extendido: las market orders no llenan de forma
            # confiable y el rebalanceo quedaría a medias (con la estrategia marcada
            # como 'rebalanceada' aunque no se haya operado). Lo bloqueamos.
            ec2.button(exec_btn, type="primary", disabled=True)
            st.warning(f"🔒 Mercado cerrado ({mk['detail']}). El rebalanceo está "
                       f"deshabilitado: fuera de la sesión regular las órdenes no llenan "
                       f"bien y dejarían el portafolio inconsistente. Próxima sesión: "
                       f"{mk['next_open_local']} (tu hora).")
        elif ec2.button(exec_btn, type="primary"):
            from src.broker.orders import execute_rebalance
            # Panel de progreso en vivo: cada mensaje del backend se escribe acá.
            with st.status("Ejecutando operaciones…", expanded=True) as status_box:
                try:
                    cb = lambda m: status_box.write(f"• {m}")
                    with ibkr_session(config, "rebalance") as conn:
                        capital = _deploy_capital(conn.get_account_summary().get("NetLiquidation", 1_000_000))
                        res = execute_rebalance(conn, target_weights, capital=capital,
                                                dry_run=False, trigger="dashboard",
                                                params=reb_params, on_progress=cb)
                    st.session_state.pop("dry_run_res", None)
                    st.session_state["last_exec"] = {**res, "capital": capital}
                    msg = f"✓ Todo operado: {res['n_filled']}/{len(res['orders'])} órdenes llenadas"
                    if res["n_pending"]:
                        msg += f" · {res['n_pending']} sin confirmar (revisá en unos seg)"
                    status_box.update(label=msg, state="complete", expanded=False)
                    _fetch_live()
                    st.rerun()
                except Exception as e:
                    status_box.update(label=f"Error al ejecutar: {e}", state="error")

        # Resumen de la última ejecución (incluye las órdenes omitidas por < 1 acción).
        le = st.session_state.get("last_exec")
        if le:
            st.success(f"Última ejecución: {le['n_filled']}/{len(le['orders'])} órdenes "
                       f"llenadas con {usd(le['capital'])} · nada pendiente"
                       if not le["n_pending"] else
                       f"Última ejecución: {le['n_filled']}/{len(le['orders'])} llenadas, "
                       f"{le['n_pending']} sin confirmar")
            if le.get("skipped"):
                with st.expander(f"ℹ️ {len(le['skipped'])} posiciones se omitieron (daban < 1 acción con este capital)"):
                    st.caption("Su peso objetivo × capital / precio daba menos de 1 acción, "
                               "y no se pueden comprar fracciones. Con más capital entrarían.")
                    st.dataframe(pd.DataFrame(le["skipped"]), use_container_width=True, hide_index=True)

        # Vista previa (dry-run): órdenes que se enviarían + las que se omitirían.
        dr = st.session_state.get("dry_run_res")
        if dr:
            st.caption(f"Vista previa: {len(dr['orders'])} órdenes a enviar"
                       + (f" · {len(dr['skipped'])} se omitirían (< 1 acción)" if dr["skipped"] else ""))
            if dr["orders"]:
                st.dataframe(pd.DataFrame(dr["orders"]), use_container_width=True, hide_index=True)
            if dr["skipped"]:
                with st.expander(f"ℹ️ {len(dr['skipped'])} posiciones omitidas (< 1 acción)"):
                    st.dataframe(pd.DataFrame(dr["skipped"]), use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # ===================== BLOQUE 2 · MONITOREAR ESTRATEGIA ACTIVA ============
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    '📊 MONITOREAR ESTRATEGIA ACTIVA <span class="panel-sub">'
                    'posiciones · P&L · drift en vivo</span></div></div>', unsafe_allow_html=True)
        if not live:
            st.info("Apretá «🔄 Actualizar portafolio» arriba (o activá Auto-refresh) para ver "
                    "posiciones, P&L y drift en vivo.")
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            portfolio_df = live["portfolio"]
            # SOLO las posiciones de la estrategia (universo de ETFs). Excluye warrants
            # y cualquier otra tenencia ajena: queremos el dinero y el P&L de NUESTRA
            # estrategia, no de la cartera entera.
            if not portfolio_df.empty:
                strat_df = portfolio_df[portfolio_df["ticker"].isin(ETF_UNIVERSE)].copy()
            else:
                strat_df = portfolio_df

            invested = float(live.get("invested", 0.0))
            # P&L ACUMULADO (realizado + no realizado), calculado en _fetch_live.
            strat_pnl = float(live.get("cum_pnl", 0.0))
            n_pos = len(strat_df)
            n_long = int((strat_df["qty"] > 0).sum()) if not strat_df.empty else 0
            n_short = n_pos - n_long
            ret_pct = (strat_pnl / invested * 100) if invested else 0.0
            pnl_txt = ("+" if strat_pnl >= 0 else "−") + usd(abs(strat_pnl))
            # Peso de cada posición como % del CAPITAL DE LA ESTRATEGIA (no de la cuenta
            # total), para que sea comparable con el peso objetivo en el drift.
            if not strat_df.empty and invested:
                strat_df["weight"] = strat_df["market_value"] / invested

            # Volatilidad anualizada estimada del portafolio actual (pesos × cov histórica).
            vol_ann = float("nan")
            if not strat_df.empty:
                vol_ann = portfolio_vol(strat_df.groupby("ticker")["weight"].sum(), returns)

            st.caption(f"Actualizado: {live['ts']} · solo posiciones de la estrategia (TSMOM)")
            strip = "".join([
                kpi("Invertido", usd(invested), "valor de mercado de la estrategia"),
                kpi("P&L de la estrategia", pnl_txt, "acumulado (real + no real.)", "",
                    f"tone-{tone(strat_pnl)}"),
                kpi("Retorno", f"{ret_pct:+.2f}%", "P&L / invertido", "accent",
                    f"tone-{tone(strat_pnl)}"),
                kpi("Vol anualizada", pct(vol_ann, 1), "estimada · cov histórica", "accent"),
                kpi("Posiciones", f"{n_pos}", f"{n_long}L · {n_short}S"),
            ])
            st.markdown(f'<div class="kpi-strip" style="grid-template-columns:repeat(5,1fr)">'
                        f'{strip}</div>', unsafe_allow_html=True)

            # ----- Gráfico de rendimiento (historial PERSISTENTE de la estrategia) -----
            # Cada refresh suma un punto a logs/nav_history.csv, que PERSISTE entre
            # sesiones (no se borra con el kill). Así, si volvés días después, ves la
            # evolución completa desde el inicio.
            nav_path = os.path.join(ROOT, "logs", "nav_history.csv")
            if os.path.exists(nav_path) and os.path.getsize(nav_path) > 1:
                nav = pd.read_csv(nav_path)
                nav["timestamp"] = pd.to_datetime(nav["timestamp"], errors="coerce")
                nav = nav.dropna(subset=["timestamp"]).sort_values("timestamp")
                st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                            'RENDIMIENTO — HISTORIAL DE LA ESTRATEGIA <span class="panel-sub">'
                            'P&L acumulado (realizado + no realizado) · no se reinicia en los '
                            'rebalanceos · persiste entre sesiones</span></div></div>',
                            unsafe_allow_html=True)
                if len(nav) >= 1:
                    desde = nav["timestamp"].iloc[0]
                    dias = (nav["timestamp"].iloc[-1] - desde).days
                    st.caption(f"Historial desde {desde:%d-%b %H:%M} · "
                               f"{dias} día{'s' if dias != 1 else ''} · {len(nav)} puntos")
                    # Ejes recalculados en cada refresh: SIEMPRE muestran todo el
                    # historial (nunca recortan) + un margen para que no quede pegado
                    # a los bordes. Incluyo el 0 porque el área se rellena hasta cero.
                    yv = nav["pnl"].astype(float)
                    ylo, yhi = min(yv.min(), 0.0), max(yv.max(), 0.0)
                    ypad = (yhi - ylo) * 0.15 or max(abs(yhi), abs(ylo), 1.0) * 0.15
                    t0, t1 = nav["timestamp"].iloc[0], nav["timestamp"].iloc[-1]
                    tpad = (t1 - t0) * 0.04 if t1 > t0 else pd.Timedelta(hours=1)
                    # Con muchos puntos, solo línea (más limpio); con pocos, línea+marcadores.
                    _mode = "lines+markers" if len(nav) <= 60 else "lines"
                    fperf = go.Figure(go.Scatter(
                        x=nav["timestamp"], y=nav["pnl"], mode=_mode,
                        line=dict(color=PAL["accent"], width=2),
                        marker=dict(color=PAL["accent"], size=4),
                        fill="tozeroy", fillcolor=T.rgba(PAL["accent"], 0.08),
                        hovertemplate="%{x|%d-%b %H:%M}<br>P&L $%{y:,.2f}<extra></extra>"))
                    fperf.add_hline(y=0, line_dash="dash", line_color=PAL["border"])
                    T.fig_layout(fperf, PAL, height=260)
                    fperf.update_yaxes(range=[ylo - ypad, yhi + ypad],
                                       tickprefix="$", tickformat=",.0f")
                    fperf.update_xaxes(range=[t0 - tpad, t1 + tpad])
                    st.plotly_chart(fperf, use_container_width=True, config={"displayModeBar": False})
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.caption("📈 El gráfico de rendimiento se va armando con cada refresh "
                           "(activá Auto-refresh para verlo evolucionar).")

            if not strat_df.empty:
                pdf = strat_df.copy()
                pdf["asset_class"] = pdf["ticker"].map(ETF_UNIVERSE)
                st.caption("Posiciones de la estrategia (tiempo real)")
                st.dataframe(
                    pdf[["ticker", "asset_class", "qty", "market_price", "market_value", "weight", "unrealized_pnl"]]
                    .sort_values("market_value", ascending=False),
                    use_container_width=True, hide_index=True)
            else:
                st.info("La estrategia no tiene posiciones abiertas todavía.")

            # Drift: solo tickers de la estrategia (groupby por si hay varios lotes).
            # Normalizamos el target al mismo gross (% de la estrategia) para que sea
            # comparable con el peso actual: así, recién ejecutada, el drift es ~0.
            cur_w = (strat_df.groupby("ticker")["weight"].sum() if not strat_df.empty
                     else pd.Series(dtype=float))
            _tgt_gross = float(target_weights.abs().sum()) or 1.0
            target_pct = target_weights / _tgt_gross
            drift_rows = []
            for tk in target_pct.index.union(cur_w.index):
                tw = float(target_pct.get(tk, 0.0))
                cw = float(cur_w.get(tk, 0.0))
                drift_rows.append({"ticker": tk, "asset_class": ETF_UNIVERSE.get(tk, "—"),
                                   "target_w": round(tw, 4), "current_w": round(cw, 4),
                                   "drift": round(tw - cw, 4)})
            drift_df = pd.DataFrame(drift_rows)
            drift_df["abs"] = drift_df["drift"].abs()
            drift_df = drift_df.sort_values("abs", ascending=False).drop(columns="abs")
            # Drift total = mitad de la suma de |drift| = fracción del portafolio que
            # habría que reasignar para volver al target (turnover de un rebalanceo).
            # Se recalcula en CADA refresh (cambia con los precios en vivo).
            drift_total = float(drift_df["drift"].abs().sum()) / 2
            # Sparkline del historial de drift (se mueve cuando el drift cambia).
            spark = ""
            if os.path.exists(nav_path) and os.path.getsize(nav_path) > 1:
                _navd = pd.read_csv(nav_path)
                if "drift" in _navd.columns and _navd["drift"].notna().sum() >= 2:
                    spark = sparkline((_navd["drift"].dropna() * 100).tail(50).tolist(),
                                      PAL["accent"], width=200, height=34)
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:2px 0">'
                f'<span style="font-size:1.3rem;font-weight:700;color:var(--accent);'
                f'font-family:\'JetBrains Mono\',monospace">Drift total: {pct(drift_total, 1)}</span>'
                f'<span class="panel-sub">actualizado {live["ts"]} · se recalcula en cada refresh</span>'
                f'<span style="flex:1;min-width:120px">{spark}</span></div>',
                unsafe_allow_html=True)
            st.caption("Cuánto del portafolio habría que reasignar para volver al target · "
                       "top 8 posiciones más desviadas:")
            st.dataframe(drift_df.head(8), use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # ----- KILL SWITCH / RESET (siempre disponible si la estrategia está enrolada) -----
        st.markdown('<div class="panel" style="border-color:var(--neg)">'
                    '<div class="panel-head"><div class="panel-title" style="color:var(--neg)">'
                    '⛔ DETENER Y CERRAR TODO <span class="panel-sub">'
                    'cierra TODAS las posiciones, detiene la estrategia y borra el historial '
                    '(operaciones + rendimiento) para empezar de cero</span></div></div>',
                    unsafe_allow_html=True)
        ck1, ck2 = st.columns([1.3, 1])
        confirm_kill = ck1.checkbox("Confirmo: cerrar todo, detener y borrar el historial")
        if ck2.button("🔪 EJECUTAR CORTE", type="primary", disabled=not confirm_kill):
            from src.broker.orders import close_all_positions, clear_trade_logs, clear_nav_history
            try:
                with ibkr_session(config, "kill") as conn:
                    closed = close_all_positions(conn, dry_run=False,
                                                 reason="kill switch (dashboard)")
                _state.stop("kill switch (dashboard)")
                # "Cerrar todas las operaciones" = empezar de cero: borra operaciones
                # Y el historial de P&L, y reinicia el tracking acumulado.
                clear_trade_logs()
                clear_nav_history()
                _state.reset_pnl()
                st.session_state.pop("dry_run_res", None)
                st.session_state.pop("last_exec", None)
                st.error(f"⛔ Estrategia DETENIDA · {len(closed)} órdenes de cierre enviadas · "
                         f"historial (operaciones + P&L) borrado. Listo para empezar de cero.")
                _fetch_live()
                st.rerun()
            except Exception as e:
                st.error(f"Error al cortar: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    # Auto-refresh: re-corre la página cada N seg (monitoreo en vivo, cualquier estado).
    if auto_refresh:
        _time.sleep(interval_secs)
        st.rerun()


# ============================================================ PÁGINA 5 · TRADE LOG

elif page.startswith("05"):
    st.markdown('<div class="page-h1">Trade Log</div>'
                '<div class="page-sub">registro de órdenes ejecutadas</div>', unsafe_allow_html=True)

    log_path = os.path.join(ROOT, "logs", "trades.csv")
    trades_df = (read_trades_csv(log_path)
                 if os.path.exists(log_path) and os.path.getsize(log_path) > 1 else None)
    if trades_df is not None:
        n_buy = int((trades_df["action"] == "BUY").sum())
        n_sell = int((trades_df["action"] == "SELL").sum())
        strip = "".join([
            kpi("Total órdenes", str(len(trades_df))),
            kpi("Compras", str(n_buy), "", "", "tone-pos"),
            kpi("Ventas", str(n_sell), "", "", "tone-neg"),
        ])
        st.markdown(f'<div class="kpi-strip" style="grid-template-columns:repeat(3,1fr)">{strip}</div>',
                    unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        tf = c1.multiselect("Ticker", sorted(trades_df["ticker"].unique()))
        af = c2.multiselect("Acción", ["BUY", "SELL"])
        df = trades_df.copy()
        if tf:
            df = df[df["ticker"].isin(tf)]
        if af:
            df = df[df["action"].isin(af)]
        st.dataframe(df.sort_values("timestamp", ascending=False),
                     use_container_width=True, hide_index=True)

        trades_df["month"] = trades_df["timestamp"].dt.to_period("M").astype(str)
        mc = trades_df.groupby("month").size().reset_index(name="count")
        fb = go.Figure(go.Bar(x=mc["month"], y=mc["count"], marker_color=PAL["accent-dim"]))
        T.fig_layout(fb, PAL, height=240)
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'ÓRDENES POR MES</div></div>', unsafe_allow_html=True)
        st.plotly_chart(fb, use_container_width=True, config={"displayModeBar": False})
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown(panel("SIN REGISTROS",
                          '<div class="mrow"><span class="mrow-k">No hay trades todavía. '
                          'Ejecutá un rebalanceo desde <b>Live Portfolio</b> para registrar operaciones.</span></div>'),
                    unsafe_allow_html=True)


# ============================================================ PÁGINA 6 · REBALANCES

elif page.startswith("06"):
    st.markdown('<div class="page-h1">Rebalances <span class="dim">— historial</span></div>'
                '<div class="page-sub">cada evento de rebalanceo y de corte ejecutado en IBKR</div>',
                unsafe_allow_html=True)

    reb_path = os.path.join(ROOT, "logs", "rebalances.csv")
    reb_df = (pd.read_csv(reb_path)
              if os.path.exists(reb_path) and os.path.getsize(reb_path) > 1 else None)
    if reb_df is not None and not reb_df.empty:
        reb_df["timestamp"] = pd.to_datetime(reb_df["timestamp"])
        n_reb = int((reb_df["trigger"] != "KILL").sum())
        n_kill = int((reb_df["trigger"] == "KILL").sum())
        last = reb_df.sort_values("timestamp").iloc[-1]
        strip = "".join([
            kpi("Eventos totales", str(len(reb_df))),
            kpi("Rebalanceos", str(n_reb), "", "", "tone-accent"),
            kpi("Cortes (kill)", str(n_kill), "", "", "tone-neg"),
            kpi("Último", last["timestamp"].strftime("%Y-%m-%d %H:%M"), str(last["trigger"])),
        ])
        st.markdown(f'<div class="kpi-strip" style="grid-template-columns:repeat(4,1fr)">{strip}</div>',
                    unsafe_allow_html=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'HISTORIAL DE REBALANCEOS</div></div>', unsafe_allow_html=True)
        st.dataframe(reb_df.sort_values("timestamp", ascending=False),
                     use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Órdenes de un rebalanceo puntual (trae trades.csv y filtra por rebalance_id)
        trades_path = os.path.join(ROOT, "logs", "trades.csv")
        tdf = (read_trades_csv(trades_path)
               if os.path.exists(trades_path) and os.path.getsize(trades_path) > 1 else None)
        if tdf is not None and "rebalance_id" in tdf.columns:
                rid = st.selectbox("Ver órdenes del rebalanceo",
                                   reb_df.sort_values("timestamp", ascending=False)["rebalance_id"])
                sub = tdf[tdf["rebalance_id"] == rid]
                st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                            f'ÓRDENES · {rid}</div></div>', unsafe_allow_html=True)
                st.dataframe(sub, use_container_width=True, hide_index=True)
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown(panel("SIN REBALANCEOS",
                          '<div class="mrow"><span class="mrow-k">Todavía no se ejecutó ningún '
                          'rebalanceo. Ejecutá uno desde <b>Live Portfolio</b>.</span></div>'),
                    unsafe_allow_html=True)
