"""A small, static symbol universe for search/autocomplete and for seeding the
simulated feed. Yahoo-style tickers (".NS" = NSE).

`ref_price` is only a seed for the simulator — real prices come from the
provider. `vol` is an annualised volatility guess used to make the simulated
series look like the real stock (PSU banks jump around, FMCG does not).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    name: str
    sector: str
    ref_price: float
    vol: float  # annualised


UNIVERSE: list[SymbolInfo] = [
    SymbolInfo("RELIANCE.NS", "Reliance Industries", "Energy", 1420, 0.22),
    SymbolInfo("TCS.NS", "Tata Consultancy Services", "IT", 3180, 0.20),
    SymbolInfo("HDFCBANK.NS", "HDFC Bank", "Banking", 1960, 0.19),
    SymbolInfo("INFY.NS", "Infosys", "IT", 1510, 0.24),
    SymbolInfo("ICICIBANK.NS", "ICICI Bank", "Banking", 1410, 0.20),
    SymbolInfo("BHARTIARTL.NS", "Bharti Airtel", "Telecom", 1880, 0.21),
    SymbolInfo("SBIN.NS", "State Bank of India", "Banking", 810, 0.27),
    SymbolInfo("ITC.NS", "ITC", "FMCG", 415, 0.17),
    SymbolInfo("LT.NS", "Larsen & Toubro", "Infrastructure", 3560, 0.22),
    SymbolInfo("HINDUNILVR.NS", "Hindustan Unilever", "FMCG", 2480, 0.16),
    SymbolInfo("KOTAKBANK.NS", "Kotak Mahindra Bank", "Banking", 2060, 0.21),
    SymbolInfo("AXISBANK.NS", "Axis Bank", "Banking", 1120, 0.25),
    SymbolInfo("BAJFINANCE.NS", "Bajaj Finance", "NBFC", 920, 0.29),
    SymbolInfo("MARUTI.NS", "Maruti Suzuki", "Auto", 12900, 0.21),
    SymbolInfo("SUNPHARMA.NS", "Sun Pharma", "Pharma", 1650, 0.20),
    SymbolInfo("TATAMOTORS.NS", "Tata Motors", "Auto", 690, 0.34),
    SymbolInfo("M&M.NS", "Mahindra & Mahindra", "Auto", 3320, 0.25),
    SymbolInfo("HCLTECH.NS", "HCL Technologies", "IT", 1470, 0.24),
    SymbolInfo("WIPRO.NS", "Wipro", "IT", 250, 0.26),
    SymbolInfo("TECHM.NS", "Tech Mahindra", "IT", 1520, 0.26),
    SymbolInfo("ASIANPAINT.NS", "Asian Paints", "Consumer", 2440, 0.20),
    SymbolInfo("TITAN.NS", "Titan Company", "Consumer", 3390, 0.24),
    SymbolInfo("ULTRACEMCO.NS", "UltraTech Cement", "Cement", 12400, 0.21),
    SymbolInfo("NTPC.NS", "NTPC", "Power", 335, 0.23),
    SymbolInfo("POWERGRID.NS", "Power Grid", "Power", 290, 0.20),
    SymbolInfo("ONGC.NS", "ONGC", "Energy", 245, 0.28),
    SymbolInfo("COALINDIA.NS", "Coal India", "Mining", 390, 0.27),
    SymbolInfo("TATASTEEL.NS", "Tata Steel", "Metals", 160, 0.33),
    SymbolInfo("JSWSTEEL.NS", "JSW Steel", "Metals", 1040, 0.30),
    SymbolInfo("HINDALCO.NS", "Hindalco", "Metals", 690, 0.31),
    SymbolInfo("ADANIENT.NS", "Adani Enterprises", "Conglomerate", 2450, 0.42),
    SymbolInfo("ADANIPORTS.NS", "Adani Ports", "Infrastructure", 1400, 0.33),
    SymbolInfo("BAJAJFINSV.NS", "Bajaj Finserv", "NBFC", 2010, 0.26),
    SymbolInfo("NESTLEIND.NS", "Nestle India", "FMCG", 2380, 0.17),
    SymbolInfo("DRREDDY.NS", "Dr. Reddy's", "Pharma", 1290, 0.23),
    SymbolInfo("CIPLA.NS", "Cipla", "Pharma", 1530, 0.22),
    SymbolInfo("DIVISLAB.NS", "Divi's Laboratories", "Pharma", 6550, 0.26),
    SymbolInfo("APOLLOHOSP.NS", "Apollo Hospitals", "Healthcare", 7400, 0.24),
    SymbolInfo("EICHERMOT.NS", "Eicher Motors", "Auto", 5600, 0.24),
    SymbolInfo("BAJAJ-AUTO.NS", "Bajaj Auto", "Auto", 8500, 0.23),
    SymbolInfo("HEROMOTOCO.NS", "Hero MotoCorp", "Auto", 4300, 0.25),
    SymbolInfo("GRASIM.NS", "Grasim Industries", "Cement", 2790, 0.23),
    SymbolInfo("INDUSINDBK.NS", "IndusInd Bank", "Banking", 830, 0.40),
    SymbolInfo("SBILIFE.NS", "SBI Life Insurance", "Insurance", 1830, 0.22),
    SymbolInfo("HDFCLIFE.NS", "HDFC Life Insurance", "Insurance", 790, 0.23),
    SymbolInfo("BPCL.NS", "BPCL", "Energy", 330, 0.30),
    SymbolInfo("TATACONSUM.NS", "Tata Consumer Products", "FMCG", 1090, 0.23),
    SymbolInfo("BRITANNIA.NS", "Britannia Industries", "FMCG", 5800, 0.18),
    SymbolInfo("TRENT.NS", "Trent", "Retail", 5400, 0.36),
    SymbolInfo("ZOMATO.NS", "Eternal (Zomato)", "Internet", 290, 0.42),
    SymbolInfo("PAYTM.NS", "One97 Communications (Paytm)", "Fintech", 1150, 0.48),
    SymbolInfo("NYKAA.NS", "FSN E-Commerce (Nykaa)", "Internet", 215, 0.40),
    SymbolInfo("IRCTC.NS", "IRCTC", "Travel", 760, 0.30),
    SymbolInfo("HAL.NS", "Hindustan Aeronautics", "Defence", 4600, 0.33),
    SymbolInfo("BEL.NS", "Bharat Electronics", "Defence", 410, 0.32),
    SymbolInfo("DLF.NS", "DLF", "Realty", 820, 0.35),
    SymbolInfo("VEDL.NS", "Vedanta", "Metals", 450, 0.36),
    SymbolInfo("YESBANK.NS", "Yes Bank", "Banking", 20, 0.45),
    SymbolInfo("IDEA.NS", "Vodafone Idea", "Telecom", 7.5, 0.60),
    SymbolInfo("SUZLON.NS", "Suzlon Energy", "Renewables", 62, 0.50),
    SymbolInfo("^NSEI", "NIFTY 50", "Index", 24800, 0.13),
    SymbolInfo("^NSEBANK", "NIFTY Bank", "Index", 55300, 0.16),
]

BY_SYMBOL: dict[str, SymbolInfo] = {s.symbol: s for s in UNIVERSE}


def search(q: str, limit: int = 8) -> list[SymbolInfo]:
    q = q.strip().upper()
    if not q:
        return UNIVERSE[:limit]
    starts = [s for s in UNIVERSE if s.symbol.startswith(q) or s.name.upper().startswith(q)]
    contains = [s for s in UNIVERSE if s not in starts and (q in s.symbol or q in s.name.upper())]
    return (starts + contains)[:limit]


def normalise(symbol: str) -> str:
    """User typed 'tcs' or 'TCS.NS' or 'tcs.ns' → 'TCS.NS'. Indices keep '^'."""
    s = symbol.strip().upper()
    if not s:
        return s
    if s.startswith("^") or "." in s:
        return s
    return f"{s}.NS"
