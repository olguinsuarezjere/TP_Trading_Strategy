"""
TSMOM Terminal — paleta y CSS estilo Bloomberg (3 temas: phosphor / amber / ice).

Tokens tomados 1:1 del design handoff (claude.ai/design) → lib/styles.css.
"""

# Tokens base (phosphor). amber/ice sobreescriben solo lo necesario.
_PHOSPHOR = {
    "bg-0": "#060809", "bg-1": "#0b0f10", "bg-2": "#12181a", "bg-3": "#1a2225",
    "border": "#1d2529", "border-soft": "#161d20",
    "grid": "rgba(130,170,160,.07)", "grid-strong": "rgba(130,170,160,.22)",
    "text": "#ccd6d2", "text-dim": "#61706c", "text-mute": "#3f4b48", "text-faint": "#3f4b48",
    "accent": "#2cf08a", "accent-dim": "#12734a", "accent-glow": "rgba(44,240,138,.5)",
    "pos": "#34e08a", "neg": "#ff5d63", "warn": "#ffb454", "info": "#4aa8ff",
}

PALETTES = {
    "phosphor": _PHOSPHOR,
    "amber": {**_PHOSPHOR,
              "bg-0": "#070605", "bg-1": "#0f0c08", "bg-2": "#181309", "bg-3": "#221a0e",
              "border": "#2a2113", "border-soft": "#1d1710",
              "grid": "rgba(190,160,110,.08)", "grid-strong": "rgba(190,160,110,.24)",
              "text": "#e2d4b8", "text-dim": "#897a5a", "text-mute": "#4d4534", "text-faint": "#4d4534",
              "accent": "#ffb000", "accent-dim": "#7a5400", "accent-glow": "rgba(255,176,0,.45)",
              "pos": "#ffb000", "neg": "#ff5533", "warn": "#ff8a3c", "info": "#6fb8ff"},
    "ice": {**_PHOSPHOR,
            "bg-0": "#05080c", "bg-1": "#0a0f15", "bg-2": "#101822", "bg-3": "#18222e",
            "border": "#1a2531", "border-soft": "#131c25",
            "grid": "rgba(120,170,200,.08)", "grid-strong": "rgba(120,170,200,.24)",
            "text": "#c4d4df", "text-dim": "#5f7282", "text-mute": "#3c4a56", "text-faint": "#3c4a56",
            "accent": "#34d6ea", "accent-dim": "#166577", "accent-glow": "rgba(52,214,234,.45)",
            "pos": "#34e08a", "neg": "#ff5d63", "warn": "#ffb454", "info": "#4aa8ff"},
    # Bloomberg clásico: negro absoluto + ámbar/naranja, verde/rojo para P&L.
    "bloomberg": {**_PHOSPHOR,
                  "bg-0": "#000000", "bg-1": "#0a0907", "bg-2": "#13110c", "bg-3": "#1d1810",
                  "border": "#2a2114", "border-soft": "#1b150d",
                  "grid": "rgba(255,150,40,.07)", "grid-strong": "rgba(255,150,40,.22)",
                  "text": "#e8e1d2", "text-dim": "#8c7a57", "text-mute": "#52462f", "text-faint": "#52462f",
                  "accent": "#ff8c1a", "accent-dim": "#7a3f00", "accent-glow": "rgba(255,140,26,.5)",
                  "pos": "#37d67a", "neg": "#ff4d4d", "warn": "#ffb454", "info": "#4aa8ff"},
    # Graphite: blanco/acero sobre carbón, sin color de marca — sobrio e institucional.
    "graphite": {**_PHOSPHOR,
                 "bg-0": "#080a0c", "bg-1": "#0f1216", "bg-2": "#161b20", "bg-3": "#1f262c",
                 "border": "#262e35", "border-soft": "#1a2027",
                 "grid": "rgba(180,195,210,.06)", "grid-strong": "rgba(180,195,210,.2)",
                 "text": "#dfe6ec", "text-dim": "#7a8794", "text-mute": "#49525b", "text-faint": "#49525b",
                 "accent": "#e6edf3", "accent-dim": "#586470", "accent-glow": "rgba(230,237,243,.28)",
                 "pos": "#3ddc84", "neg": "#ff5d63", "warn": "#ffb454", "info": "#5aa9ff"},
}

MONO = '"IBM Plex Mono","JetBrains Mono","SF Mono",ui-monospace,Menlo,monospace'


def rgba(hex_or_rgba: str, alpha: float) -> str:
    """Convierte '#rrggbb' (o pasa 'rgba(...)') a 'rgba(r,g,b,alpha)' — Plotly no acepta hex de 8 dígitos."""
    c = hex_or_rgba.strip()
    if c.startswith("#") and len(c) >= 7:
        r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return c


def root_vars(theme: str) -> str:
    pal = PALETTES.get(theme, _PHOSPHOR)
    body = "".join(f"--{k}:{v};" for k, v in pal.items())
    return ":root{" + body + f"--mono:{MONO};--pad:13px;--gap:9px;--radius:0px;" + "}"


# CSS estático (usa var(--xxx)). NO es f-string: no escapar llaves.
BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');

/* ---- ocultar chrome de Streamlit ---- */
#MainMenu, header[data-testid="stHeader"], footer { display:none !important; }
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { display:none !important; }

html { font-size: 13px; }
html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"] {
    background: var(--bg-0) !important; color: var(--text);
    font-family: var(--mono) !important; font-variant-numeric: tabular-nums; letter-spacing:-.01em;
}
.block-container {
    padding: 0.45rem 1.05rem 2rem 1.05rem !important; max-width: 100% !important;
    background:
      radial-gradient(900px 480px at 80% -8%, color-mix(in srgb, var(--accent) 4%, transparent), transparent 70%);
}
[data-testid="stVerticalBlock"] { gap: 0.5rem; }
[data-testid="column"] { gap:0 !important; }
::selection { background: var(--accent-dim); color: var(--text); }
::-webkit-scrollbar { width:9px; height:9px; }
::-webkit-scrollbar-track { background: var(--bg-0); }
::-webkit-scrollbar-thumb { background: var(--bg-3); border:2px solid var(--bg-0); }
::-webkit-scrollbar-thumb:hover { background: var(--accent-dim); }

/* ---- sidebar como rail terminal ---- */
section[data-testid="stSidebar"] { background: var(--bg-1) !important; border-right:1px solid var(--border); width:230px !important; }
section[data-testid="stSidebar"] > div { padding-top: 0.6rem; }
section[data-testid="stSidebar"] * { font-family: var(--mono) !important; }
.side-head { display:flex; align-items:center; gap:10px; padding:2px 2px 11px; border-bottom:1px solid var(--border); margin-bottom:10px;}
.side-logo { width:30px;height:30px;border:1px solid var(--accent);display:flex;align-items:center;justify-content:center;
             color:var(--accent);font-weight:700;text-shadow:0 0 10px var(--accent-glow);}
.side-title { color:var(--text); font-weight:700; font-size:15px; letter-spacing:1px; line-height:1;}
.side-sub { color:var(--text-faint); font-size:9px; letter-spacing:2px; margin-top:4px;}
.side-label { color:var(--text-faint); font-size:9.5px; letter-spacing:2.5px; margin:8px 0 3px; text-transform:uppercase; }
.side-foot { border-top:1px solid var(--border); margin-top:8px; padding-top:8px; }
.foot-row { display:flex; justify-content:space-between; font-size:10.5px; color:var(--text-dim); padding:2px 0; }
.foot-row b { color:var(--text); }

/* nav radio → items numerados con borde accent */
section[data-testid="stSidebar"] [role="radiogroup"] { gap:1px; }
section[data-testid="stSidebar"] [role="radiogroup"] label {
    border-left:2px solid transparent; padding:6px 10px !important; margin:0 !important; border-radius:0;
    color:var(--text-dim); font-size:12px; letter-spacing:.5px; transition:all .12s;
}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover { background:var(--bg-2); color:var(--text); }
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    border-left-color:var(--accent); color:var(--accent);
    background:color-mix(in srgb, var(--accent) 8%, transparent);
}
section[data-testid="stSidebar"] [role="radiogroup"] label p { color:var(--text-dim); font-size:12px; }
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p { color:var(--accent); }
/* sliders accent */
section[data-testid="stSidebar"] [data-testid="stSlider"] [role="slider"]{ background:var(--accent)!important; box-shadow:0 0 6px var(--accent-glow)!important;}
section[data-testid="stSidebar"] [data-testid="stSlider"] [data-baseweb="slider"] div[style*="background"]{ background:var(--accent)!important;}
section[data-testid="stSidebar"] [data-testid="stTickBar"]{ display:none; }
section[data-testid="stSidebar"] label p { color:var(--text-dim); font-size:11px; letter-spacing:.06em; }

/* ---- status bar ---- */
.topbar { display:flex; align-items:center; justify-content:space-between; background:var(--bg-1);
          border:1px solid var(--border); padding:5px 11px; margin-bottom:8px; font-size:11.5px; height:30px;}
.tb-left, .tb-right { display:flex; align-items:center; gap:12px; white-space:nowrap; }
.tb-left { overflow:hidden; }
.tb-brand { color:var(--accent); font-weight:700; letter-spacing:1px; text-shadow:0 0 8px var(--accent-glow); }
.tb-brand span { color:var(--text-dim); font-weight:400; }
.tb-sep { color:var(--text-faint); }
.tb-tag { color:var(--text); font-weight:600; }
.tb-muted { color:var(--text-dim); overflow:hidden; text-overflow:ellipsis; }
.tb-chip { border:1px solid var(--border); padding:1px 7px; color:var(--text-dim); font-size:11px; }
.tb-chip b { color:var(--text); }
.tb-chip.accent { border-color:var(--accent-dim); color:var(--accent); }
.dot { display:inline-block; width:6px;height:6px;border-radius:50%; background:var(--accent); margin-right:5px;
       box-shadow:0 0 6px var(--accent); animation:pulse 2s infinite; }
@keyframes pulse { 50%{opacity:.35} }

/* ---- panels ---- */
.panel { background:var(--bg-1); border:1px solid var(--border); margin-bottom:9px; }
.panel-head { display:flex; align-items:center; justify-content:space-between; padding:9px 13px; border-bottom:1px solid var(--border); }
.panel-title { color:var(--text); font-size:11.5px; font-weight:600; letter-spacing:1.4px; text-transform:uppercase; display:flex; align-items:center; gap:8px; }
.panel-title::before { content:"▎"; color:var(--accent); text-shadow:0 0 6px var(--accent-glow); }
.panel-sub { color:var(--text-dim); font-size:10px; font-weight:400; letter-spacing:.4px; text-transform:none; }
.panel-body { padding:13px; }

/* ---- KPI tiles ---- */
.kpi-strip { display:grid; grid-template-columns:repeat(5,1fr); gap:9px; margin-bottom:9px; }
.kpi { background:var(--bg-1); border:1px solid var(--border); padding:11px 13px; position:relative; overflow:hidden; }
.kpi::before { content:""; position:absolute; left:0; top:0; bottom:0; width:2px; background:var(--accent); opacity:.5; }
.kpi-label { color:var(--text-dim); font-size:9.5px; letter-spacing:1.8px; text-transform:uppercase; }
.kpi-value { color:var(--text); font-size:1.7rem; font-weight:700; line-height:1; margin-top:7px; letter-spacing:-.02em; }
.kpi-delta { font-size:10px; margin-top:6px; color:var(--text-dim); }
.kpi-value.accent { color:var(--accent); text-shadow:0 0 12px var(--accent-glow); }
.tone-pos{color:var(--pos)!important;} .tone-neg{color:var(--neg)!important;} .tone-accent{color:var(--accent)!important;} .tone-dim{color:var(--text-dim)!important;}

/* ---- signal matrix ---- */
.sig-class { margin-bottom:14px; }
.sig-class-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:7px; padding-bottom:4px; border-bottom:1px solid var(--border-soft); }
.sig-class-name { color:var(--text); font-size:11.5px; letter-spacing:1.3px; text-transform:uppercase; }
.sig-class-meta { color:var(--text-dim); font-size:10px; }
.sig-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(78px,1fr)); gap:4px; }
.sig-pos { color:var(--pos); } .sig-neg { color:var(--neg); }
.sigcell { position:relative; border:1px solid var(--border); border-radius:2px; padding:5px 7px 6px;
           background:color-mix(in srgb, currentColor calc(var(--int) * 17%), var(--bg-2));
           transition:transform .08s, border-color .12s; cursor:pointer; }
.sigcell:hover { transform:translateY(-1px); border-color:currentColor; z-index:2; }
.sigcell[open] { border-color:currentColor; z-index:30; }
.sigcell > summary { list-style:none; display:block; outline:none; }
.sigcell > summary::-webkit-details-marker { display:none; }
.sig-tk { font-size:.74rem; font-weight:600; display:block; }
.sigcell.sig-pos .sig-tk { color:color-mix(in srgb, var(--pos) 70%, var(--text)); }
.sigcell.sig-neg .sig-tk { color:color-mix(in srgb, var(--neg) 70%, var(--text)); }
.sig-bar { display:block; height:3px; background:var(--bg-0); margin-top:4px; border-radius:2px; overflow:hidden; }
.sig-bar span { display:block; height:100%; background:currentColor; }
/* panel desplegable al hacer click en un ETF */
.sig-pop { position:absolute; top:calc(100% + 5px); left:0; z-index:40; cursor:default;
           width:236px; max-width:74vw; padding:10px 12px;
           background:var(--bg-1); border:1px solid var(--border); border-radius:4px;
           box-shadow:0 8px 26px rgba(0,0,0,.5); color:var(--text); }
.sig-pop-name { font-size:11.5px; font-weight:700; line-height:1.25; color:var(--text); }
.sig-pop-desc { font-size:10.5px; line-height:1.45; color:var(--text-dim); margin-top:4px; }
.sig-pop-metrics { display:flex; gap:14px; margin-top:9px; padding-top:8px; border-top:1px solid var(--border-soft); }
.sig-pop-metrics > span { display:flex; flex-direction:column; gap:2px;
                          font-size:9px; letter-spacing:.6px; text-transform:uppercase; color:var(--text-faint); }
.sig-pop-metrics b { font-size:12.5px; font-weight:700; letter-spacing:0; color:var(--text);
                     font-family:'JetBrains Mono', ui-monospace, monospace; }

/* ---- NAV hero ---- */
.nav-val { color:var(--text); font-size:2.6rem; font-weight:700; line-height:1; letter-spacing:-.02em; }
.nav-delta { font-size:.92rem; font-weight:600; margin-top:3px; }
.nav-foot { display:flex; justify-content:space-around; color:var(--text-dim); font-size:10.5px; margin-top:12px; }
.nav-foot b { color:var(--text); }

/* ---- exposure bars ---- */
.ac-row { display:grid; grid-template-columns:84px 1fr 50px; align-items:center; gap:8px; margin-bottom:7px; }
.ac-name { color:var(--text-dim); font-size:11px; }
.ac-track { display:flex; height:9px; background:var(--bg-2); overflow:hidden; }
.ac-fill.pos { background:var(--pos); } .ac-fill.neg { background:var(--neg); }
.ac-meta { color:var(--text-faint); font-size:10px; text-align:right; }
.ac-pie-head { display:flex; justify-content:space-between; align-items:baseline;
               margin:6px 0 -6px; padding-bottom:3px; border-bottom:1px solid var(--border-soft); }
.ac-pie-name { color:var(--text); font-size:11px; letter-spacing:1.2px; text-transform:uppercase; }
.ac-pie-meta { color:var(--text-dim); font-size:10px; font-family:var(--mono); font-variant-numeric:tabular-nums; letter-spacing:.04em; }
.ac-foot { color:var(--text-dim); font-size:10.5px; margin-top:8px; line-height:1.5; }
.ac-foot b { color:var(--text); } .ac-foot b.pos{color:var(--pos);} .ac-foot b.neg{color:var(--neg);}

/* ---- metrics table ---- */
.mtable { width:100%; }
.mrow { display:flex; justify-content:space-between; padding:6px 2px; border-bottom:1px solid var(--border-soft); font-size:12px; }
.mrow:last-child { border-bottom:none; }
.mrow-k { color:var(--text-dim); }
.mrow-v { color:var(--text); font-weight:600; }

/* ---- streamlit nativos: dataframe / tabs ---- */
[data-testid="stDataFrame"] { border:1px solid var(--border); }
.stTabs [data-baseweb="tab-list"] { gap:2px; border-bottom:1px solid var(--border); }
.stTabs [data-baseweb="tab"] { background:none; border:none; border-bottom:2px solid transparent; color:var(--text-dim);
    font-family:var(--mono); font-size:11.5px; letter-spacing:.05em; text-transform:uppercase; padding:7px 15px;}
.stTabs [aria-selected="true"] { color:var(--accent); border-bottom-color:var(--accent); }
[data-testid="stToggle"] *, .stButton button, [data-testid="stNumberInput"] * { font-family:var(--mono) !important; }
.stButton button { border:1px solid var(--border); background:var(--bg-1); color:var(--text); border-radius:0; font-size:12px; }
.stButton button:hover { border-color:var(--accent-dim); color:var(--accent); }

h1,h2,h3 { font-family:var(--mono)!important; color:var(--text)!important; }
.page-h1 { font-size:1.15rem; font-weight:700; color:var(--text); margin:2px 0 0; letter-spacing:-.01em; }
.page-h1 .dim { color:var(--text-dim); font-weight:400; }
.page-sub { color:var(--text-dim); font-size:10.5px; margin:3px 0 10px; letter-spacing:.3px; }

/* ---- overlay de cálculo del óptimo (lookback × target vol) ---- */
.calc-overlay {
    position:fixed; top:0; right:0; bottom:0; left:230px; z-index:9999;
    display:flex; align-items:center; justify-content:center;
    background:color-mix(in srgb, var(--bg-0) 86%, transparent); backdrop-filter:blur(3px);
    animation:calc-fade .18s ease-out;
}
@media (max-width:900px) { .calc-overlay { left:0; } }
@keyframes calc-fade { from{opacity:0} to{opacity:1} }
.calc-card {
    background:var(--bg-1); border:1px solid var(--accent-dim); padding:34px 46px; min-width:440px; max-width:90vw;
    box-shadow:0 0 0 1px var(--bg-0), 0 24px 70px rgba(0,0,0,.6), 0 0 40px var(--accent-glow);
    text-align:center;
}
.calc-eyebrow { color:var(--text-dim); font-size:10px; letter-spacing:3px; text-transform:uppercase; margin-bottom:14px; }
.calc-title { color:var(--accent); font-size:1.25rem; font-weight:700; letter-spacing:.5px;
    text-shadow:0 0 16px var(--accent-glow); margin-bottom:8px; }
.calc-sub { color:var(--text); font-size:12px; line-height:1.6; margin-bottom:22px; }
.calc-sub b { color:var(--accent); }
.calc-bar { height:4px; background:var(--bg-3); overflow:hidden; position:relative; }
.calc-bar::after { content:""; position:absolute; top:0; left:0; height:100%; width:40%;
    background:linear-gradient(90deg, transparent, var(--accent), transparent);
    box-shadow:0 0 10px var(--accent-glow); animation:calc-sweep 1.1s ease-in-out infinite; }
@keyframes calc-sweep { 0%{left:-40%} 100%{left:100%} }
.calc-foot { color:var(--text-dim); font-size:10px; letter-spacing:1.5px; margin-top:14px; }
.calc-foot .dot { width:6px; height:6px; }
"""


def inject(theme: str) -> str:
    return "<style>" + root_vars(theme) + BASE_CSS + "</style>"


def fig_layout(fig, pal: dict, height: int = 300, legend: bool = False):
    """Aplica el tema terminal a una figura Plotly."""
    fig.update_layout(
        paper_bgcolor=pal["bg-1"], plot_bgcolor=pal["bg-1"],
        font=dict(family="IBM Plex Mono, monospace", size=11, color=pal["text-dim"]),
        margin=dict(l=52, r=18, t=18, b=30), height=height, showlegend=legend,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=pal["text-dim"], size=10),
                    orientation="h", y=1.1, x=0),
        hoverlabel=dict(bgcolor=pal["bg-2"], font=dict(family="IBM Plex Mono, monospace", color=pal["text"])),
    )
    fig.update_xaxes(gridcolor=pal["grid"], zerolinecolor=pal["grid-strong"], linecolor=pal["border"],
                     tickfont=dict(color=pal["text-mute"], size=10))
    fig.update_yaxes(gridcolor=pal["grid"], zerolinecolor=pal["grid-strong"], linecolor=pal["border"],
                     tickfont=dict(color=pal["text-mute"], size=10))
    return fig
