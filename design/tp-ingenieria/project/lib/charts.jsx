/* charts.jsx — SVG charts themed via CSS vars (--accent, --pos, --neg, --grid…).
   All exported to window for cross-script use. */
const { useState, useRef, useEffect, useCallback } = React;

// measure a container's pixel width (responsive SVG)
function useMeasure() {
  const ref = useRef(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(e.contentRect.width);
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function niceTicks(min, max, n) {
  const span = max - min || 1;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const start = Math.ceil(min / step) * step;
  const out = [];
  for (let v = start; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

// ---------------------------------------------------------------- LineChart
// series: [{ key, values:[], color, dash, label }]
function LineChart({ dates, series, height = 320, log = false, yFmt, valueFmt }) {
  const [ref, w] = useMeasure();
  const [hover, setHover] = useState(null);
  const pad = { t: 14, r: 16, b: 26, l: 56 };
  const iw = Math.max(10, w - pad.l - pad.r);
  const ih = height - pad.t - pad.b;
  const n = dates.length;

  const all = series.flatMap((s) => s.values);
  let lo = Math.min(...all), hi = Math.max(...all);
  const tf = (v) => (log ? Math.log(v) : v);
  let ymin = tf(lo), ymax = tf(hi);
  const padY = (ymax - ymin) * 0.06; ymin -= padY; ymax += padY;
  const x = (i) => pad.l + (n <= 1 ? 0 : (i / (n - 1)) * iw);
  const y = (v) => pad.t + ih - ((tf(v) - ymin) / (ymax - ymin || 1)) * ih;

  const yticks = log
    ? niceTicks(lo, hi, 5).filter((v) => v > 0)
    : niceTicks(lo, hi, 5);
  const xtickIdx = [];
  const step = Math.max(1, Math.round(n / 6));
  for (let i = 0; i < n; i += step) xtickIdx.push(i);

  const onMove = useCallback((e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    let i = Math.round(((px - pad.l) / iw) * (n - 1));
    i = Math.max(0, Math.min(n - 1, i));
    setHover(i);
  }, [iw, n]);

  return (
    <div ref={ref} style={{ position: "relative", width: "100%" }}>
      <svg width={w} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)}
           style={{ display: "block", cursor: "crosshair" }}>
        {yticks.map((v, k) => (
          <g key={k}>
            <line x1={pad.l} x2={pad.l + iw} y1={y(v)} y2={y(v)} stroke="var(--grid)" strokeWidth="1" />
            <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" className="ch-axis">{yFmt ? yFmt(v) : v.toFixed(2)}</text>
          </g>
        ))}
        {xtickIdx.map((i) => (
          <text key={i} x={x(i)} y={height - 8} textAnchor="middle" className="ch-axis">{dates[i].label}</text>
        ))}
        {series.map((s) => {
          const d = s.values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
          return <path key={s.key} d={d} fill="none" stroke={s.color} strokeWidth={s.width || 2}
                       strokeDasharray={s.dash || "0"} strokeLinejoin="round" />;
        })}
        {hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="var(--text-dim)" strokeWidth="1" strokeDasharray="2,3" />
            {series.map((s) => (
              <circle key={s.key} cx={x(hover)} cy={y(s.values[hover])} r="3.2" fill={s.color} stroke="var(--bg-1)" strokeWidth="1.5" />
            ))}
          </g>
        )}
      </svg>
      {hover != null && (
        <div className="ch-tip" style={{
          left: Math.min(Math.max(x(hover) + 10, 8), w - 150),
          top: pad.t + 4,
        }}>
          <div className="ch-tip-date">{dates[hover].label}</div>
          {series.map((s) => (
            <div key={s.key} className="ch-tip-row">
              <span className="ch-tip-dot" style={{ background: s.color }}></span>
              <span className="ch-tip-lbl">{s.label}</span>
              <span className="ch-tip-val">{valueFmt ? valueFmt(s.values[hover]) : s.values[hover].toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------- LineChart + crises
function CrisisLineChart({ dates, values, crises, height = 320 }) {
  const [ref, w] = useMeasure();
  const [hover, setHover] = useState(null);
  const pad = { t: 14, r: 16, b: 26, l: 56 };
  const iw = Math.max(10, w - pad.l - pad.r), ih = height - pad.t - pad.b, n = dates.length;
  let lo = Math.min(...values), hi = Math.max(...values);
  const ymin = Math.log(lo) - 0.04, ymax = Math.log(hi) + 0.04;
  const x = (i) => pad.l + (i / (n - 1)) * iw;
  const y = (v) => pad.t + ih - ((Math.log(v) - ymin) / (ymax - ymin)) * ih;
  const yticks = niceTicks(lo, hi, 5).filter((v) => v > 0);
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    let i = Math.round(((e.clientX - rect.left - pad.l) / iw) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  return (
    <div ref={ref} style={{ position: "relative", width: "100%" }}>
      <svg width={w} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} style={{ display: "block", cursor: "crosshair" }}>
        {crises.map((c, k) => (
          <g key={k}>
            <rect x={x(c.si)} y={pad.t} width={Math.max(2, x(c.ei - 1) - x(c.si))} height={ih}
                  fill="var(--neg)" opacity="0.10" />
            <text x={x(c.si) + 4} y={pad.t + 12} className="ch-crisis-lbl">{c.name}</text>
          </g>
        ))}
        {yticks.map((v, k) => (
          <g key={k}>
            <line x1={pad.l} x2={pad.l + iw} y1={y(v)} y2={y(v)} stroke="var(--grid)" />
            <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" className="ch-axis">{v.toFixed(1)}×</text>
          </g>
        ))}
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" />
        {hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="var(--text-dim)" strokeDasharray="2,3" />
            <circle cx={x(hover)} cy={y(values[hover])} r="3.2" fill="var(--accent)" stroke="var(--bg-1)" strokeWidth="1.5" />
          </g>
        )}
      </svg>
      {hover != null && (
        <div className="ch-tip" style={{ left: Math.min(Math.max(x(hover) + 10, 8), w - 130), top: pad.t + 4 }}>
          <div className="ch-tip-date">{dates[hover].label}</div>
          <div className="ch-tip-row"><span className="ch-tip-lbl">NAV</span><span className="ch-tip-val">{values[hover].toFixed(3)}×</span></div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------- Drawdown
function DrawdownChart({ dates, values, height = 180 }) {
  const [ref, w] = useMeasure();
  const [hover, setHover] = useState(null);
  const pad = { t: 10, r: 16, b: 22, l: 56 };
  const iw = Math.max(10, w - pad.l - pad.r), ih = height - pad.t - pad.b, n = dates.length;
  const lo = Math.min(...values);
  const x = (i) => pad.l + (i / (n - 1)) * iw;
  const y = (v) => pad.t + (v / (lo || -1)) * ih;
  const area = `M${x(0)},${y(0)} ` + values.map((v, i) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ") + ` L${x(n - 1)},${y(0)} Z`;
  const line = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const yticks = niceTicks(lo, 0, 4);
  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    let i = Math.round(((e.clientX - rect.left - pad.l) / iw) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  return (
    <div ref={ref} style={{ position: "relative", width: "100%" }}>
      <svg width={w} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} style={{ display: "block", cursor: "crosshair" }}>
        {yticks.map((v, k) => (
          <g key={k}>
            <line x1={pad.l} x2={pad.l + iw} y1={y(v)} y2={y(v)} stroke="var(--grid)" />
            <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" className="ch-axis">{(v * 100).toFixed(0)}%</text>
          </g>
        ))}
        <path d={area} fill="var(--neg)" opacity="0.18" />
        <path d={line} fill="none" stroke="var(--neg)" strokeWidth="1.5" />
        {hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="var(--text-dim)" strokeDasharray="2,3" />
            <circle cx={x(hover)} cy={y(values[hover])} r="3" fill="var(--neg)" stroke="var(--bg-1)" strokeWidth="1.5" />
          </g>
        )}
      </svg>
      {hover != null && (
        <div className="ch-tip" style={{ left: Math.min(Math.max(x(hover) + 10, 8), w - 120), top: pad.t }}>
          <div className="ch-tip-date">{dates[hover].label}</div>
          <div className="ch-tip-row"><span className="ch-tip-lbl">DD</span><span className="ch-tip-val" style={{ color: "var(--neg)" }}>{(values[hover] * 100).toFixed(1)}%</span></div>
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------- BarChart
// data:[{label, value}], signed colours
function BarChart({ data, height = 240, fmt, highlight }) {
  const [ref, w] = useMeasure();
  const [hover, setHover] = useState(null);
  const pad = { t: 12, r: 12, b: 26, l: 44 };
  const iw = Math.max(10, w - pad.l - pad.r), ih = height - pad.t - pad.b;
  const vals = data.map((d) => d.value);
  const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
  const y = (v) => pad.t + (hi - v) / ((hi - lo) || 1) * ih;
  const bw = iw / data.length;
  return (
    <div ref={ref} style={{ position: "relative", width: "100%" }}>
      <svg width={w} height={height} style={{ display: "block" }}>
        <line x1={pad.l} x2={pad.l + iw} y1={y(0)} y2={y(0)} stroke="var(--grid-strong)" />
        {data.map((d, i) => {
          const bx = pad.l + i * bw + bw * 0.16;
          const bwid = bw * 0.68;
          const top = d.value >= 0 ? y(d.value) : y(0);
          const h = Math.abs(y(d.value) - y(0));
          const col = d.color || (d.value >= 0 ? "var(--pos)" : "var(--neg)");
          const isHi = highlight != null && data[i].label === highlight;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={bx} y={top} width={bwid} height={Math.max(1, h)} fill={col}
                    opacity={hover == null || hover === i ? 1 : 0.5}
                    stroke={isHi ? "var(--text)" : "none"} strokeWidth={isHi ? 1.2 : 0} />
              <text x={bx + bwid / 2} y={height - 9} textAnchor="middle" className="ch-axis">{d.label}</text>
            </g>
          );
        })}
        {hover != null && (
          <text x={pad.l + hover * bw + bw / 2}
                y={(data[hover].value >= 0 ? y(data[hover].value) : y(0)) - 5}
                textAnchor="middle" className="ch-barval">{fmt ? fmt(data[hover].value) : data[hover].value}</text>
        )}
      </svg>
    </div>
  );
}

// ------------------------------------------------------------------- Donut
function Donut({ data, size = 168, fmt }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = size / 2, ir = r * 0.62;
  let a0 = -Math.PI / 2;
  const arcs = data.map((d) => {
    const frac = d.value / total;
    const a1 = a0 + frac * Math.PI * 2;
    const big = a1 - a0 > Math.PI ? 1 : 0;
    const p = (a, rad) => [r + rad * Math.cos(a), r + rad * Math.sin(a)];
    const [x0, y0] = p(a0, r), [x1, y1] = p(a1, r);
    const [x2, y2] = p(a1, ir), [x3, y3] = p(a0, ir);
    const d_ = `M${x0},${y0} A${r},${r} 0 ${big} 1 ${x1},${y1} L${x2},${y2} A${ir},${ir} 0 ${big} 0 ${x3},${y3} Z`;
    a0 = a1;
    return { d: d_, color: d.color, label: d.label, frac };
  });
  return (
    <svg width={size} height={size} style={{ display: "block" }}>
      {arcs.map((a, i) => <path key={i} d={a.d} fill={a.color} stroke="var(--bg-1)" strokeWidth="1.5" />)}
    </svg>
  );
}

// --------------------------------------------------------------- Sparkline
function Sparkline({ values, width = 120, height = 30, color = "var(--accent)" }) {
  const lo = Math.min(...values), hi = Math.max(...values);
  const x = (i) => (i / (values.length - 1)) * width;
  const y = (v) => height - ((v - lo) / ((hi - lo) || 1)) * height;
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

Object.assign(window, { useMeasure, LineChart, CrisisLineChart, DrawdownChart, BarChart, Donut, Sparkline });
