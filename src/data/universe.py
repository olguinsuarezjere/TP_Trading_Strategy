"""
Universo de ETFs — única fuente de verdad del proyecto.

Reglas del universo (para que el backtest sea representativo de lo que se puede
ejecutar de verdad en Interactive Brokers):

  1. Todos los ETFs son US-listed y denominados en USD. No se incluyen ETFs
     extranjeros (.MI de Milán, .TO de Toronto, etc.) porque sus retornos
     mezclan el movimiento del activo con el del tipo de cambio EUR/CAD vs USD,
     lo que contamina una estrategia 100% en USD.
  2. Se incluyen ETFs sin importar cuándo arrancaron: cada uno se usa DESDE SU
     INCEPTION. Los meses previos a que existiera quedan NaN y el pipeline los
     trata como "activo inactivo" (peso 0), sin lookahead. El único requisito es
     tener historia mínima para formar señal (data.min_history_months en
     config.yaml). scripts/fetch_missing_etfs.py valida USD + historia mínima;
     lo que no pasa NO entra acá.
  3. La clase de activo de cada ticker se usa para (a) el dashboard y (b) el
     weighting 'class_balanced' (presupuesto igual por clase). Con el default
     'pooled' (1/N global) la clase solo afecta la visualización.
  4. CURACIÓN POR LIQUIDEZ (corr >= 0.95): siguiendo Moskowitz et al. (2012), que
     usa 1 instrumento líquido por mercado, agrupamos los ETFs por correlación de
     retornos mensuales (complete-linkage, corr >= 0.95 = "mismo mercado") y nos
     quedamos con el MÁS LÍQUIDO de cada grupo (mayor dollar-volume). Los 72
     redundantes están en REDUNDANT_TICKERS (con el ticker que los reemplaza) y se
     filtran del universo activo. ETF_UNIVERSE pasa de 205 a 133 mercados distintos.
     Análisis: scripts/universe_redundancy.py · comparación: scripts/compare_universe_backtest.py
     Para volver a los 205, basta vaciar REDUNDANT_TICKERS (los datos siguen en el parquet).

Mantener sincronizado con el parquet: `python main.py data-status` muestra si
universe.py y Data/etf_prices.parquet quedaron desalineados, y
`python main.py update-data` / scripts/fetch_missing_etfs.py descarga lo que
falte.
"""

# Universo crudo (205 ETFs US-listed en USD). ETF_UNIVERSE se deriva de acá
# filtrando los redundantes (ver REDUNDANT_TICKERS más abajo).
_ALL_ETFS: dict[str, str] = {
    # ===================================================================
    # EQUITY
    # ===================================================================
    # --- US large cap / total market ---
    "SPY":  "equity", "IVV":  "equity", "VOO":  "equity", "VTI":  "equity",
    "ITOT": "equity", "QQQ":  "equity", "DIA":  "equity", "OEF":  "equity",
    "RSP":  "equity", "IWB":  "equity",
    # --- US mid / small cap ---
    "IWM":  "equity", "IJR":  "equity", "MDY":  "equity", "IJH":  "equity",
    "VO":   "equity", "VB":   "equity",
    # --- US style (value / growth) ---
    "VTV":  "equity", "VUG":  "equity", "IWD":  "equity", "IWF":  "equity",
    "IWN":  "equity", "IWO":  "equity", "VBR":  "equity", "VBK":  "equity",
    # --- US factors ---
    "MTUM": "equity", "QUAL": "equity", "VLUE": "equity", "USMV": "equity",
    "SIZE": "equity", "SPLV": "equity", "SPHB": "equity", "MOAT": "equity",
    "VIG":  "equity", "VYM":  "equity", "SDY":  "equity", "NOBL": "equity",
    "DGRO": "equity", "SCHD": "equity",
    # --- US sectors (SPDR Select, los 11) ---
    "XLF":  "equity", "XLE":  "equity", "XLK":  "equity", "XLV":  "equity",
    "XLI":  "equity", "XLY":  "equity", "XLP":  "equity", "XLU":  "equity",
    "XLB":  "equity", "XLRE": "equity", "XLC":  "equity",
    # --- US industries / thematic ---
    "SMH":  "equity", "SOXX": "equity", "IBB":  "equity", "XBI":  "equity",
    "KRE":  "equity", "KBE":  "equity", "ITB":  "equity", "XHB":  "equity",
    "KIE":  "equity", "OIH":  "equity", "XOP":  "equity", "XME":  "equity",
    "GDX":  "equity", "GDXJ": "equity", "SIL":  "equity", "URA":  "equity",
    "TAN":  "equity", "ICLN": "equity", "WOOD": "equity", "MOO":  "equity",
    "IYT":  "equity", "ITA":  "equity", "SKYY": "equity", "IGV":  "equity",
    "FDN":  "equity", "XRT":  "equity", "IHI":  "equity", "JETS": "equity",
    "HACK": "equity", "CIBR": "equity", "KWEB": "equity", "BOTZ": "equity",
    "LIT":  "equity", "REMX": "equity", "COPX": "equity",
    # --- US real estate (REIT) ---
    "IYR":  "equity", "VNQ":  "equity", "SCHH": "equity", "REZ":  "equity",
    "REM":  "equity",
    # --- International developed ---
    "EFA":  "equity", "IEFA": "equity", "VEA":  "equity", "VGK":  "equity",
    "EZU":  "equity", "FEZ":  "equity", "EWJ":  "equity", "EWG":  "equity",
    "EWU":  "equity", "EWL":  "equity", "EWP":  "equity", "EWI":  "equity",
    "EWQ":  "equity", "EWD":  "equity", "EWN":  "equity", "EWK":  "equity",
    "EWA":  "equity", "EWC":  "equity", "EWH":  "equity", "EWS":  "equity",
    "EWT":  "equity", "IEV":  "equity",
    # --- Emerging markets ---
    "EEM":  "equity", "IEMG": "equity", "VWO":  "equity", "EWZ":  "equity",
    "MCHI": "equity", "FXI":  "equity", "INDA": "equity", "EPI":  "equity",
    "EWW":  "equity", "EZA":  "equity", "EWM":  "equity", "EWY":  "equity",
    "EPOL": "equity", "TUR":  "equity", "EPHE": "equity", "THD":  "equity",
    "VNM":  "equity", "ILF":  "equity", "AFK":  "equity",

    # ===================================================================
    # BOND
    # ===================================================================
    # --- US treasury (por duración) ---
    "SHY":  "bond", "IEI":  "bond", "IEF":  "bond", "TLH":  "bond",
    "TLT":  "bond", "GOVT": "bond", "SHV":  "bond", "BIL":  "bond",
    "VGSH": "bond", "VGIT": "bond", "VGLT": "bond", "EDV":  "bond",
    "SGOV": "bond",
    # --- US aggregate / investment grade corp ---
    "AGG":  "bond", "BND":  "bond", "LQD":  "bond", "VCIT": "bond",
    "VCSH": "bond", "IGSB": "bond", "IGIB": "bond", "USIG": "bond",
    # --- US high yield / bank loans ---
    "HYG":  "bond", "JNK":  "bond", "SJNK": "bond", "ANGL": "bond",
    "BKLN": "bond", "USHY": "bond",
    # --- US inflation-protected ---
    "TIP":  "bond", "VTIP": "bond", "SCHP": "bond", "STIP": "bond",
    # --- US municipal ---
    "MUB":  "bond", "TFI":  "bond",
    # --- US mortgage-backed ---
    "MBB":  "bond", "VMBS": "bond",
    # --- International / EM bonds ---
    "BNDX": "bond", "BWX":  "bond", "IGOV": "bond", "EMB":  "bond",
    "EMLC": "bond", "PCY":  "bond",

    # ===================================================================
    # COMMODITY
    # ===================================================================
    # --- broad ---
    "DBC":  "commodity", "GSG":  "commodity", "DJP":  "commodity",
    "PDBC": "commodity", "COMT": "commodity", "BCI":  "commodity",
    # --- precious metals ---
    "GLD":  "commodity", "IAU":  "commodity", "SGOL": "commodity",
    "SLV":  "commodity", "SIVR": "commodity", "PPLT": "commodity",
    "PALL": "commodity",
    # --- energy ---
    "USO":  "commodity", "BNO":  "commodity", "UNG":  "commodity",
    "UGA":  "commodity", "DBO":  "commodity", "DBE":  "commodity",
    # --- agriculture ---
    "DBA":  "commodity", "CORN": "commodity", "WEAT": "commodity",
    "SOYB": "commodity", "CANE": "commodity",
    # --- industrial metals ---
    "DBB":  "commodity", "CPER": "commodity",

    # ===================================================================
    # CURRENCY / FX
    # ===================================================================
    "UUP":  "currency", "UDN":  "currency", "FXE":  "currency",
    "FXB":  "currency", "FXY":  "currency", "FXA":  "currency",
    "FXC":  "currency", "FXF":  "currency",
}

# Tickers REDUNDANTES sacados por la curación de liquidez (corr >= 0.95).
# Cada uno se consolida en el ETF más líquido de su grupo (flecha "→ KEPT").
# Quitar una línea de acá = volver a incluir ese ETF en el universo activo.
REDUNDANT_TICKERS: dict[str, str] = {
    # --- equity ---
    "HACK": "→ CIBR",
    "VIG": "→ DIA",
    "IEMG": "→ EEM",
    "VWO": "→ EEM",
    "IEFA": "→ EFA",
    "VEA": "→ EFA",
    "ILF": "→ EWZ",
    "MCHI": "→ FXI",
    "GDXJ": "→ GDX",
    "MDY": "→ IJH",
    "VB": "→ IJH",
    "VBR": "→ IJH",
    "EPI": "→ INDA",
    "XHB": "→ ITB",
    "IJR": "→ IWM",
    "IWN": "→ IWM",
    "VBK": "→ IWO",
    "SCHH": "→ IYR",
    "VNQ": "→ IYR",
    "XLRE": "→ IYR",
    "KBE": "→ KRE",
    "SDY": "→ NOBL",
    "IWF": "→ QQQ",
    "VUG": "→ QQQ",
    "SIZE": "→ RSP",
    "VO": "→ RSP",
    "SOXX": "→ SMH",
    "ITOT": "→ SPY",
    "IVV": "→ SPY",
    "IWB": "→ SPY",
    "OEF": "→ SPY",
    "QUAL": "→ SPY",
    "VOO": "→ SPY",
    "VTI": "→ SPY",
    "EWQ": "→ VGK",
    "EZU": "→ VGK",
    "FEZ": "→ VGK",
    "IEV": "→ VGK",
    "DGRO": "→ VTV",
    "IWD": "→ VTV",
    "VYM": "→ VTV",
    # --- bond ---
    "BND": "→ AGG",
    "IGOV": "→ BWX",
    "PCY": "→ EMB",
    "JNK": "→ HYG",
    "SJNK": "→ HYG",
    "USHY": "→ HYG",
    "IEI": "→ IEF",
    "VGIT": "→ IEF",
    "IGIB": "→ LQD",
    "USIG": "→ LQD",
    "VCIT": "→ LQD",
    "VMBS": "→ MBB",
    "TFI": "→ MUB",
    "BIL": "→ SGOV",
    "SHV": "→ SGOV",
    "VGSH": "→ SHY",
    "SCHP": "→ TIP",
    "EDV": "→ TLT",
    "TLH": "→ TLT",
    "VGLT": "→ TLT",
    "IGSB": "→ VCSH",
    "STIP": "→ VTIP",
    # --- commodity ---
    "DJP": "→ BCI",
    "GSG": "→ BNO",
    "DBE": "→ DBO",
    "IAU": "→ GLD",
    "SGOL": "→ GLD",
    "COMT": "→ PDBC",
    "DBC": "→ PDBC",
    "SIVR": "→ SLV",
    # --- currency ---
    "UDN": "→ FXE",
}

# Universo ACTIVO = crudo menos los redundantes. Única fuente de verdad del backtest.
ETF_UNIVERSE: dict[str, str] = {
    t: c for t, c in _ALL_ETFS.items() if t not in REDUNDANT_TICKERS
}

ASSET_CLASSES = ["equity", "bond", "commodity", "currency"]

# Tickers que estuvieron en el parquet pero se EXCLUYEN del universo a propósito.
# Se documentan acá para que `data-status` no los reporte como sorpresa y para
# dejar registro del motivo. Los .MI/.TO cotizan en EUR/CAD (ruido de FX).
EXCLUDED_TICKERS: dict[str, str] = {
    "COFF.MI": "Café (Milán) — cotiza en EUR, ruido de FX",
    "COTN.MI": "Algodón (Milán) — cotiza en EUR, ruido de FX",
    "NICK.MI": "Níquel (Milán) — cotiza en EUR, ruido de FX",
    "TINM.MI": "Estaño (Milán) — cotiza en EUR, ruido de FX",
    "COW.TO":  "Ganadería (Toronto) — cotiza en CAD, ruido de FX",
}
