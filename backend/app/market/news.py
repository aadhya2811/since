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


def _query_for(symbol: str, company: str) -> str:
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

_GENERIC = [
    (6, 11, 0, "{c} Q1 results in line with estimates; margin outlook steady", "Economic Times"),
    (9, 16, 5, "{c} announces dividend, record date fixed", "Business Standard"),
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
        items = _SCRIPTED.get(symbol)
        if items is None:
            c = BY_SYMBOL[symbol].name if symbol in BY_SYMBOL else company
            items = [(a, h, m, t.format(c=c), s) for a, h, m, t, s in _GENERIC]
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
