/* components.jsx — terminal UI primitives. Exported to window. */
const { useState: useStateC, useEffect: useEffectC } = React;
const D = window.TSMOM;

// blinking clock + connection status
function StatusBar({ params }) {
  const [now, setNow] = useStateC(new Date());
  useEffectC(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const t = now.toLocaleTimeString("en-GB", { hour12: false });
  return (
    <div className="statusbar">
      <div className="sb-left">
        <span className="sb-brand">TSMOM<span className="sb-brand-dim">·TERMINAL</span></span>
        <span className="sb-sep">│</span>
        <span className="sb-tag">F414 · UdeSA</span>
        <span className="sb-sep">│</span>
        <span className="sb-muted">Time Series Momentum · 66 ETFs</span>
      </div>
      <div className="sb-right">
        <span className="sb-chip"><span className="dot dot-live"></span>PAPER · IBKR 7497</span>
        <span className="sb-chip">LB {params.lookback}m</span>
        <span className="sb-chip">TV {(params.targetVol * 100).toFixed(0)}%</span>
        <span className="sb-chip sb-chip-accent">{params.signal.toUpperCase()}</span>
        <span className="sb-sep">│</span>
        <span className="sb-clock">{t} <span className="sb-muted">UTC-3</span></span>
        <span className="cursor-blink">█</span>
      </div>
    </div>
  );
}

const NAV = [
  { id: "overview", n: "01", label: "OVERVIEW", glyph: "◳" },
  { id: "backtest", n: "02", label: "BACKTEST", glyph: "◧" },
  { id: "robustness", n: "03", label: "ROBUSTNESS", glyph: "◈" },
  { id: "live", n: "04", label: "LIVE PORTFOLIO", glyph: "◉" },
  { id: "trades", n: "05", label: "TRADE LOG", glyph: "≣" },
];

function Sidebar({ page, setPage, params, setParams }) {
  return (
    <aside className="sidebar">
      <div className="side-head">
        <div className="side-logo">▚▞</div>
        <div>
          <div className="side-title">TSMOM</div>
          <div className="side-sub">SYSTEM v2.1</div>
        </div>
      </div>

      <nav className="side-nav">
        <div className="side-label">NAVEGACIÓN</div>
        {NAV.map((item) => (
          <button key={item.id} className={`navitem ${page === item.id ? "active" : ""}`}
                  onClick={() => setPage(item.id)}>
            <span className="navnum">{item.n}</span>
            <span className="navlabel">{item.label}</span>
            {page === item.id && <span className="navmark">◂</span>}
          </button>
        ))}
      </nav>

      <div className="side-params">
        <div className="side-label">PARÁMETROS</div>

        <div className="param">
          <div className="param-top"><span>LOOKBACK</span><span className="param-val">{params.lookback}m</span></div>
          <input type="range" min="3" max="24" step="1" value={params.lookback}
                 onChange={(e) => setParams({ ...params, lookback: +e.target.value })} />
        </div>

        <div className="param">
          <div className="param-top"><span>TARGET VOL</span><span className="param-val">{(params.targetVol * 100).toFixed(0)}%</span></div>
          <input type="range" min="0.05" max="0.40" step="0.01" value={params.targetVol}
                 onChange={(e) => setParams({ ...params, targetVol: +e.target.value })} />
        </div>

        <div className="param">
          <div className="param-top"><span>SEÑAL</span></div>
          <div className="seg">
            {["binary", "strength"].map((s) => (
              <button key={s} className={params.signal === s ? "on" : ""}
                      onClick={() => setParams({ ...params, signal: s })}>{s}</button>
            ))}
          </div>
        </div>

        <div className="param param-range">
          <div className="param-top"><span>VENTANA</span></div>
          <div className="daterange">2015-01 → 2024-12</div>
        </div>
      </div>

      <div className="side-foot">
        <div className="foot-row"><span>UNIVERSO</span><b>66 ETF</b></div>
        <div className="foot-row"><span>REBAL</span><b>MENSUAL</b></div>
        <div className="foot-row"><span>CAPITAL</span><b>$1.00M</b></div>
      </div>
    </aside>
  );
}

// generic panel with terminal header
function Panel({ title, right, sub, children, className = "", flush }) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <header className="panel-head">
          <div className="panel-title">
            <span className="panel-tick">▍</span>{title}
            {sub && <span className="panel-sub">{sub}</span>}
          </div>
          {right && <div className="panel-right">{right}</div>}
        </header>
      )}
      <div className={flush ? "panel-body flush" : "panel-body"}>{children}</div>
    </section>
  );
}

// KPI tile
function Kpi({ label, value, delta, deltaTone, mono = true, big }) {
  return (
    <div className={`kpi ${big ? "kpi-big" : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${mono ? "mono" : ""}`}>{value}</div>
      {delta != null && <div className={`kpi-delta tone-${deltaTone || "dim"}`}>{delta}</div>}
    </div>
  );
}

function Tag({ tone = "dim", children }) {
  return <span className={`tag tag-${tone}`}>{children}</span>;
}

function SignalCell({ s, onHover }) {
  const intensity = Math.min(1, Math.abs(s.strength) / 3);
  const tone = s.dir === 1 ? "pos" : "neg";
  return (
    <div className={`sigcell sig-${tone}`}
         style={{ "--int": intensity.toFixed(2) }}
         onMouseEnter={(e) => onHover && onHover(s, e)}
         onMouseLeave={() => onHover && onHover(null)}>
      <span className="sig-tk">{s.ticker}</span>
      <span className="sig-bar"><span style={{ width: `${intensity * 100}%` }}></span></span>
    </div>
  );
}

Object.assign(window, { StatusBar, Sidebar, Panel, Kpi, Tag, SignalCell, NAV });
