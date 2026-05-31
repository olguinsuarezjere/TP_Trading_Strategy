/* pages1.jsx — Overview + Backtest. Exported to window. */
const { useState: useS1, useMemo: useMemo1 } = React;
const T = window.TSMOM;
const F = T.fmt;

// signal strength tooltip (shared)
function useSigTip() {
  const [tip, setTip] = useS1(null);
  const onHover = (s, e) => {
    if (!s) { setTip(null); return; }
    const r = e.currentTarget.getBoundingClientRect();
    setTip({ s, x: r.left + r.width / 2, y: r.top });
  };
  const node = tip ? (
    React.createElement("div", {
      className: "sig-tip",
      style: { position: "fixed", left: tip.x, top: tip.y - 8, transform: "translate(-50%,-100%)" },
    },
      React.createElement("div", { className: "sig-tip-tk" }, tip.s.ticker,
        React.createElement("span", { className: `sig-tip-dir ${tip.s.dir === 1 ? "pos" : "neg"}` }, tip.s.dir === 1 ? "LONG" : "SHORT")),
      React.createElement("div", { className: "sig-tip-row" }, "class ",
        React.createElement("b", null, T.AC_LABEL[tip.s.ac])),
      React.createElement("div", { className: "sig-tip-row" }, "strength ",
        React.createElement("b", { className: tip.s.dir === 1 ? "pos" : "neg" }, tip.s.strength.toFixed(2)))
    )
  ) : null;
  return [onHover, node];
}

function OverviewPage({ params }) {
  const [onHover, tipNode] = useSigTip();
  const sinceInception = T.equityNet[T.equityNet.length - 1] - 1;
  const last12 = T.equityNet.slice(-13).map((v, i, a) => v); // for sparkline

  const acStats = T.ASSET_CLASSES.map((ac) => {
    const arr = T.signals.filter((s) => s.ac === ac);
    const long = arr.filter((s) => s.dir === 1).length;
    return { ac, total: arr.length, long, short: arr.length - long };
  });

  return (
    <div className="page">
      <div className="page-head">
        <h1>Time Series Momentum — <span className="dim">Overview</span></h1>
        <div className="page-sub">Señales del próximo rebalanceo · corte 2024-12 · lookback {params.lookback}m</div>
      </div>

      <div className="kpi-strip">
        <Kpi label="UNIVERSO" value="66" delta="ETFs · 4 clases" />
        <Kpi label="SHARPE (IS)" value={T.metrics.sharpe.toFixed(2)} delta="2015–2024" deltaTone="accent" />
        <Kpi label="RET. DESDE INICIO" value={F.pctSigned(sinceInception, 1)} delta="neto de costos" deltaTone="pos" />
        <Kpi label="NET EXPOSURE" value={F.pctSigned(T.netExposure, 0)} delta={`${T.nLong}L · ${T.nShort}S`} deltaTone={T.netExposure >= 0 ? "pos" : "neg"} />
        <Kpi label="POSICIONES" value={`${T.nLong + T.nShort}`} delta="todas activas" />
      </div>

      <div className="grid-2-1">
        <Panel title="SEÑAL TSMOM — MATRIZ DE ACTIVOS" sub="hover = strength"
               right={<div className="legend"><span className="lg pos">█ LONG</span><span className="lg neg">█ SHORT</span><span className="lg dim">▓ intensidad = |señal|</span></div>}>
          <div className="sig-classes">
            {T.ASSET_CLASSES.map((ac) => {
              const arr = T.signals.filter((s) => s.ac === ac);
              return (
                <div key={ac} className="sig-class">
                  <div className="sig-class-head">
                    <span className="sig-class-name">{T.AC_LABEL[ac]}</span>
                    <span className="sig-class-meta">{arr.length} · {arr.filter((s) => s.dir === 1).length}L/{arr.filter((s) => s.dir === -1).length}S</span>
                  </div>
                  <div className="sig-grid">
                    {arr.map((s) => <SignalCell key={s.ticker} s={s} onHover={onHover} />)}
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>

        <div className="stack">
          <Panel title="NAV DESDE INICIO" sub="base 1.00×">
            <div className="nav-hero">
              <div className="nav-hero-val mono">{T.equityNet[T.equityNet.length - 1].toFixed(3)}×</div>
              <div className="nav-hero-delta pos">{F.pctSigned(sinceInception, 1)}</div>
              <Sparkline values={T.equityNet} width={240} height={48} />
              <div className="nav-hero-foot">
                <span>vol {F.pct(T.metrics.annVol, 1)}</span>
                <span>maxDD <b className="neg">{F.pct(T.metrics.maxDD, 1)}</b></span>
                <span>calmar {T.metrics.calmar.toFixed(2)}</span>
              </div>
            </div>
          </Panel>

          <Panel title="EXPOSICIÓN POR CLASE">
            <div className="ac-bars">
              {acStats.map((a) => (
                <div key={a.ac} className="ac-row">
                  <span className="ac-name">{T.AC_LABEL[a.ac]}</span>
                  <div className="ac-track">
                    <div className="ac-fill pos" style={{ width: `${(a.long / a.total) * 100}%` }}></div>
                    <div className="ac-fill neg" style={{ width: `${(a.short / a.total) * 100}%` }}></div>
                  </div>
                  <span className="ac-meta mono">{a.long}/{a.short}</span>
                </div>
              ))}
            </div>
            <div className="ac-foot">
              Net exposure agregado <b className={T.netExposure >= 0 ? "pos" : "neg"}>{F.pctSigned(T.netExposure, 0)}</b> ·
              gross 100% · {T.nLong} long / {T.nShort} short
            </div>
          </Panel>
        </div>
      </div>
      {tipNode}
    </div>
  );
}

function MetricRow({ k, v, tone }) {
  return (
    <div className="mrow">
      <span className="mrow-k">{k}</span>
      <span className={`mrow-v mono ${tone || ""}`}>{v}</span>
    </div>
  );
}

function BacktestPage({ params }) {
  const [log, setLog] = useS1(true);
  const [showGross, setShowGross] = useS1(true);
  const m = T.metrics;

  const series = useMemo1(() => {
    const s = [{ key: "net", label: "Neto", values: T.equityNet, color: "var(--accent)", width: 2 }];
    if (showGross) s.push({ key: "gross", label: "Bruto", values: T.equityGross, color: "var(--text-dim)", dash: "3,3", width: 1.5 });
    return s;
  }, [showGross]);

  const maxAbs = Math.max(...T.netRet.map((r) => Math.abs(r)));

  return (
    <div className="page">
      <div className="page-head">
        <h1>Backtest — <span className="dim">Resultados</span></h1>
        <div className="page-sub">2015-01 → 2024-12 · {m.months} meses · costos {(T.config.bidAsk * 1e4).toFixed(0)}bps spread + {(T.config.commission * 1e4).toFixed(0)}bps comisión</div>
      </div>

      <div className="kpi-strip k5">
        <Kpi label="SHARPE RATIO" value={m.sharpe.toFixed(2)} delta="rf = 0" deltaTone="accent" big />
        <Kpi label="ANN. RETURN" value={F.pct(m.annReturn, 1)} delta="neto" deltaTone="pos" big />
        <Kpi label="ANN. VOLATILITY" value={F.pct(m.annVol, 1)} delta={`target ${F.pct(params.targetVol, 0)}`} big />
        <Kpi label="MAX DRAWDOWN" value={F.pct(m.maxDD, 1)} delta="peak-to-trough" deltaTone="neg" big />
        <Kpi label="CALMAR RATIO" value={m.calmar.toFixed(2)} delta="ret/maxDD" deltaTone="accent" big />
      </div>

      <Panel title="CURVA DE CAPITAL" sub="escala log"
             right={
               <div className="ctrl-row">
                 <button className={`tbtn ${showGross ? "on" : ""}`} onClick={() => setShowGross(!showGross)}>BRUTO</button>
                 <button className={`tbtn ${log ? "on" : ""}`} onClick={() => setLog(!log)}>LOG</button>
               </div>
             }>
        <LineChart dates={T.dates} series={series} height={300} log={log}
                   yFmt={(v) => `${v.toFixed(1)}×`} valueFmt={(v) => `${v.toFixed(3)}×`} />
      </Panel>

      <div className="grid-2-eq">
        <Panel title="DRAWDOWN" sub="underwater">
          <DrawdownChart dates={T.dates} values={T.drawdown} height={190} />
        </Panel>
        <Panel title="MÉTRICAS DE PERFORMANCE">
          <div className="mtable">
            <MetricRow k="Annualized Return" v={F.pct(m.annReturn, 2)} tone="pos" />
            <MetricRow k="Annualized Volatility" v={F.pct(m.annVol, 2)} />
            <MetricRow k="Sharpe Ratio" v={m.sharpe.toFixed(2)} tone="accent" />
            <MetricRow k="Sortino Ratio" v={m.sortino.toFixed(2)} tone="accent" />
            <MetricRow k="Max Drawdown" v={F.pct(m.maxDD, 2)} tone="neg" />
            <MetricRow k="Calmar Ratio" v={m.calmar.toFixed(2)} />
            <MetricRow k="Hit Rate" v={F.pct(m.hitRate, 1)} />
            <MetricRow k="Avg Monthly Turnover" v={F.pct(m.turnover, 1)} />
            <MetricRow k="Num Months" v={`${m.months}`} />
          </div>
        </Panel>
      </div>

      <Panel title="RETORNOS MENSUALES" sub="% · verde = ganancia">
        <div className="heatmap">
          <div className="hm-corner"></div>
          {["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"].map((mo) => (
            <div key={mo} className="hm-colh">{mo}</div>
          ))}
          <div className="hm-colh hm-ytd">YTD</div>
          {T.heatmap.map((row) => {
            const present = row.months.filter((x) => x != null);
            const ytd = present.reduce((p, r) => p * (1 + r), 1) - 1;
            return (
              <React.Fragment key={row.year}>
                <div className="hm-rowh">{row.year}</div>
                {row.months.map((r, i) => (
                  <div key={i} className={`hm-cell ${r == null ? "empty" : r >= 0 ? "pos" : "neg"}`}
                       style={r == null ? {} : { "--o": (Math.min(1, Math.abs(r) / maxAbs) * 0.85 + 0.12).toFixed(2) }}
                       title={r == null ? "" : `${row.year}-${String(i + 1).padStart(2, "0")}: ${F.pctSigned(r, 1)}`}>
                    {r == null ? "" : (r * 100).toFixed(1)}
                  </div>
                ))}
                <div className={`hm-cell hm-ytd ${ytd >= 0 ? "pos" : "neg"}`} style={{ "--o": "0.9" }}>
                  {F.pctSigned(ytd, 1)}
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

Object.assign(window, { OverviewPage, BacktestPage });
