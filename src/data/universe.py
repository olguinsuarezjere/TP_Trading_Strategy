ETF_UNIVERSE: dict[str, str] = {
    # Equities - US
    "SPY":  "equity", "QQQ":  "equity", "IWM":  "equity", "MDY":  "equity",
    "DIA":  "equity", "VTI":  "equity", "IVV":  "equity", "VOO":  "equity",
    # Equities - International
    "EFA":  "equity", "EEM":  "equity", "VEA":  "equity", "VWO":  "equity",
    "EWJ":  "equity", "EWG":  "equity", "EWU":  "equity", "EWZ":  "equity",
    "EWC":  "equity", "EWA":  "equity", "EWH":  "equity", "EWS":  "equity",
    "EWL":  "equity", "EWP":  "equity", "EWI":  "equity", "EWQ":  "equity",
    "EWD":  "equity", "EWN":  "equity", "EWK":  "equity",
    # Equities - Sector
    "XLF":  "equity", "XLE":  "equity", "XLK":  "equity", "XLV":  "equity",
    "XLI":  "equity", "XLY":  "equity", "XLP":  "equity", "XLU":  "equity",
    "XLB":  "equity", "XLRE": "equity",
    # Bonds - US
    "TLT":  "bond",   "IEF":  "bond",   "SHY":  "bond",   "AGG":  "bond",
    "LQD":  "bond",   "HYG":  "bond",   "TIP":  "bond",   "BND":  "bond",
    # Bonds - International
    "BNDX": "bond",   "EMB":  "bond",
    # Commodities
    "GLD":  "commodity", "SLV":  "commodity", "USO":  "commodity",
    "UNG":  "commodity", "DBA":  "commodity", "DBB":  "commodity",
    "DBC":  "commodity", "PDBC": "commodity", "CORN": "commodity",
    "WEAT": "commodity", "SOYB": "commodity", "CANE": "commodity",
    "CPER": "commodity",
    # Currencies / FX
    "UUP":  "currency", "FXE":  "currency", "FXB":  "currency",
    "FXY":  "currency", "FXA":  "currency", "FXC":  "currency",
    "FXF":  "currency",
}

ASSET_CLASSES = ["equity", "bond", "commodity", "currency"]
