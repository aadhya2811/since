"""News providers: headlines per company, keyless.

Google News RSS is used because it needs no API key, covers Indian business
press well, and returns publisher + timestamp. The simulated provider emits
headlines timed to the simulated price events so a demo shows the "here's
probably why" pairing without network access.

No sentiment model. Headlines are surfaced as *context* for a move, not
scored — a classifier trained on nothing would be noise dressed as insight.
The seam is here if one is wanted later.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..util import utcnow
from . import calendar as cal
from .provider import ProviderError
from .universe import BY_SYMBOL

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsData:
    guid: str
    title: str
    url: str
    source: str
    published_at: datetime  # UTC naive


class NewsProvider(ABC):
    name = "base"

    @abstractmethod
    async def get_news(self, symbol: str, company: str) -> list[NewsData]: ...


# ------------------------------------------------------------ Google News RSS

_GN = "https://news.google.com/rss/search"
_STRIP_SUFFIX = re.compile(r"\s+(Ltd|Limited|Industries|Company)\.?$", re.I)

# Market-wide topics, stored as pseudo-symbols so they flow through exactly the
# same fetch → store → diff pipeline as a company. A watchlist app whose news
# page only knows about your twelve stocks isn't a news page.
MARKET_TOPICS: dict[str, tuple[str, str]] = {
    "^MARKET": ("Indian markets", '(Nifty OR Sensex) (market OR stocks OR rally OR selloff) when:3d'),
    "^POLICY": ("Policy & macro", '(RBI OR SEBI OR "repo rate" OR inflation OR "GDP") India (markets OR stocks OR economy) when:7d'),
    "^FLOWS": ("Money flows", '(FII OR DII OR "foreign investors" OR "mutual fund inflows") India equities when:7d'),
    "^IPO": ("IPOs & listings", '(IPO OR listing OR "listed at") India NSE when:7d'),
}

# The names that move the index. Their news is fetched whether or not anyone
# here follows them, so the market feed has substance on day one.
HEADLINE_SYMBOLS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
                    "BHARTIARTL.NS", "SBIN.NS", "LT.NS"]


def _query_for(symbol: str, company: str) -> str:
    if symbol in MARKET_TOPICS:
        return MARKET_TOPICS[symbol][1]
    base = _STRIP_SUFFIX.sub("", company).strip()
    # "Eternal (Zomato)" → Zomato ; "One97 Communications (Paytm)" → Paytm
    m = re.search(r"\(([^)]+)\)", base)
    if m:
        base = m.group(1)
    return f'"{base}" (shares OR stock OR NSE) when:7d'


class GoogleNewsProvider(NewsProvider):
    name = "google-news"

    def __init__(self, timeout: float = 8.0, max_concurrency: int = 4):
        self._timeout = timeout
        self._sem = asyncio.Semaphore(max_concurrency)

    async def get_news(self, symbol: str, company: str) -> list[NewsData]:
        params = {"q": _query_for(symbol, company), "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
        async with self._sem:
            try:
                async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                    r = await client.get(_GN, params=params, headers={"User-Agent": "Mozilla/5.0"})
            except httpx.HTTPError as e:
                raise ProviderError(f"google news network error: {e}") from e
        if r.status_code >= 400:
            raise ProviderError(f"google news HTTP {r.status_code}")
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            raise ProviderError("google news malformed RSS") from e
        out: list[NewsData] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate")
            src = item.find("source")
            if not title or not link or not pub:
                continue
            try:
                dt = parsedate_to_datetime(pub).astimezone(timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
            # Google appends " - Publisher" to titles; the <source> tag has it cleanly.
            source = (src.text or "").strip() if src is not None else ""
            if source and title.endswith(f" - {source}"):
                title = title[: -len(source) - 3].strip()
            guid = (item.findtext("guid") or link)
            out.append(NewsData(guid=hashlib.sha1(guid.encode()).hexdigest()[:24], title=title, url=link,
                                source=source or "Google News", published_at=dt))
        out.sort(key=lambda n: n.published_at, reverse=True)
        return out[:20]


# --------------------------------------------------------------- simulated

# (sessions_ago, hour_ist, minute_ist, title, source) — timed to the price events in simulated.py
_SCRIPTED: dict[str, list[tuple[int, int, int, str, str]]] = {
    "TMPV.NS": [
        (0, 9, 32, "Tata Motors slides as JLR flags softer demand in Europe, trims FY guidance", "Economic Times"),
        (0, 11, 5, "Brokerages cut Tata Motors targets after JLR commentary; stock down 5%", "Moneycontrol"),
        (4, 15, 50, "Tata Motors to invest ₹15,000 crore in EV capacity by 2028", "Business Standard"),
    ],
    "INDUSINDBK.NS": [
        (1, 9, 20, "IndusInd Bank falls after RBI seeks clarification on derivatives accounting", "Mint"),
        (1, 14, 10, "IndusInd Bank says impact of accounting review is 'limited', stock still down 4%", "Reuters"),
        (0, 10, 45, "Analysts split on IndusInd after second day of selling", "Economic Times"),
    ],
    "HAL.NS": [
        (2, 8, 55, "HAL bags ₹26,000 crore order for 97 Tejas Mk1A fighters", "The Hindu BusinessLine"),
        (1, 12, 30, "Defence stocks rally; HAL near record high on order visibility", "Moneycontrol"),
    ],
    "BAJFINANCE.NS": [
        (0, 9, 15, "Bajaj Finance jumps on strong Q2 update: AUM up 27%, new loans up 18%", "CNBC-TV18"),
    ],
    "ETERNAL.NS": [
        (3, 10, 0, "Eternal shares surge on Blinkit's first profitable quarter", "Economic Times"),
        (0, 9, 40, "Eternal slips as Swiggy announces quick-commerce price war", "Mint"),
    ],
    "SUZLON.NS": [
        (0, 9, 18, "Suzlon hits 52-week high after 1.2 GW order from NTPC Green", "Business Standard"),
        (0, 13, 20, "Suzlon: brokerages raise targets, flag valuation risk", "Moneycontrol"),
    ],
}

# Market-wide scripted headlines for the offline demo, so the News page has a
# realistic lead story without network access.
_SCRIPTED_MARKET: dict[str, list[tuple[int, int, int, str, str]]] = {
    "^MARKET": [
        (0, 15, 45, "Nifty ends lower for a second session as IT and banks drag; Sensex down 412 points", "Economic Times"),
        (0, 9, 25, "Markets open cautious ahead of US inflation print; metals buck the trend", "Mint"),
        (1, 16, 10, "Nifty snaps four-day winning run; broader market outperforms", "Business Standard"),
        (2, 15, 55, "Sensex reclaims 82,000 as defence and renewables lead a broad rally", "Moneycontrol"),
    ],
    "^POLICY": [
        (1, 11, 30, "RBI holds repo rate at 5.75%, flags food inflation as the key risk", "Reuters"),
        (3, 14, 20, "SEBI tightens disclosure norms for related-party transactions", "The Hindu BusinessLine"),
    ],
    "^FLOWS": [
        (0, 18, 5, "FIIs sell ₹3,240 crore of Indian equities; DIIs absorb most of it", "Economic Times"),
        (2, 17, 40, "Equity mutual fund inflows stay above ₹40,000 crore for a fifth month", "Mint"),
    ],
    "^IPO": [
        (1, 10, 15, "Two mainboard IPOs open next week; grey market premiums cool off", "Moneycontrol"),
        (4, 12, 0, "Recent listings: three of five trade below issue price a month on", "Business Standard"),
    ],
}

# A pool of plausible company stories. Each simulated company draws three of
# them deterministically from its ticker, so an offline demo doesn't read like
# the same sentence pasted twelve times.
_GENERIC_POOL = [
    (0, 12, 40, "{c} gains as brokerages nudge up target prices", "Moneycontrol"),
    (0, 10, 15, "{c} slips despite in-line quarter; margin guidance in focus", "Economic Times"),
    (0, 14, 5, "Volumes spike in {c} ahead of index rebalancing", "Mint"),
    (1, 11, 30, "{c} board approves ₹1,200 crore capex plan", "Business Standard"),
    (1, 15, 40, "{c}: promoter stake unchanged, FII holding up 40 bps", "CNBC-TV18"),
    (2, 11, 0, "{c} results in line with estimates; margin outlook steady", "Economic Times"),
    (2, 16, 20, "Analysts stay split on {c} after the quarter", "Reuters"),
    (3, 9, 50, "{c} to add capacity at its southern plant", "The Hindu BusinessLine"),
    (4, 13, 10, "What the last six months tell you about {c}", "Moneycontrol"),
    (5, 16, 5, "{c} announces dividend, record date fixed", "Business Standard"),
]


class SimulatedNewsProvider(NewsProvider):
    name = "simulated-news"

    def __init__(self, *, fail: bool = False):
        self.fail = fail

    async def get_news(self, symbol: str, company: str) -> list[NewsData]:
        if self.fail:
            raise ProviderError("simulated news outage")
        now = utcnow()
        st = cal.market_state(now)
        last_completed = cal.previous_trading_day(st.session_date) if st.is_open else st.session_date
        items = _SCRIPTED_MARKET.get(symbol) or _SCRIPTED.get(symbol)
        if items is None and symbol in MARKET_TOPICS:
            items = []
        if items is None:
            c = BY_SYMBOL[symbol].name if symbol in BY_SYMBOL else company
            rng = random.Random(int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16))
            picked = rng.sample(_GENERIC_POOL, 3)
            items = [(a, h, m, t.format(c=c), s) for a, h, m, t, s in picked]
        out = []
        for ago, hh, mm, title, source in items:
            d = last_completed
            for _ in range(ago):
                d = cal.previous_trading_day(d)
            if st.is_open and ago == 0:
                d = st.session_date  # "today's" headline lands during the live session
            ts = datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm)
            ts_utc = ts - timedelta(hours=5, minutes=30)
            if ts_utc > now:
                continue
            guid = hashlib.sha1(f"{symbol}|{title}".encode()).hexdigest()[:24]
            out.append(NewsData(guid=guid, title=title, url=f"https://news.example.com/{guid}", source=source, published_at=ts_utc))
        out.sort(key=lambda n: n.published_at, reverse=True)
        return out
