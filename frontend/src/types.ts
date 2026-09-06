export interface User { id: number; email: string }

export interface ItemOut { symbol: string; name: string; position: number; added_at: string }
export interface Watchlist { id: number; name: string; version: number; updated_at: string; items: ItemOut[] }

export interface Freshness { status: 'live' | 'delayed' | 'closed' | 'stale' | 'missing'; label: string; as_of: string | null; fetched_at: string | null; source: string | null; delay_minutes: number | null }
export interface QuoteOut {
  price: number; prev_close: number | null; open: number | null; day_high: number | null; day_low: number | null
  volume: number | null; day_change_pct: number | null; freshness: Freshness
}
export interface Unusual { label: 'Unchanged' | 'Ordinary' | 'Notable' | 'Rare' | 'Extreme'; text: string; z: number | null; typical_move_pct: number; typical_window_pct: number | null }
export interface SinceOut {
  baseline_price: number; baseline_as_of: string; seen_at: string; seen_label: string
  change_abs: number; change_pct: number; sessions: number; z: number | null; same_print: boolean; unusual: Unusual
}
export interface Reason { kind: string; severity: 'high' | 'medium' | 'low'; text: string }
export interface Level { id: number; symbol: string; price: number; direction: 'above' | 'below'; note: string | null; created_at: string }
export interface NewsOut { title: string; url: string; source: string; published_at: string; is_new: boolean }

export type Tier = 'attention' | 'notable' | 'quiet'
export type Verdict = 'holds' | 'weakened' | 'broken'

export interface ThesisReview {
  id: number; verdict: Verdict; note: string | null; trigger: string; trigger_text: string | null
  price_at_review: number | null; change_pct: number | null; sessions: number | null; created_at: string
}
export interface Thesis {
  id: number; symbol: string; name: string; text: string; status: 'open' | 'closed'
  created_at: string; anchored_at: string; age_label: string
  anchor_price: number | null; price: number | null; change_pct: number | null
  sessions: number; z: number | null
  review_due: boolean; trigger: string | null; trigger_text: string | null
  review_count: number; last_verdict: Verdict | null; last_reviewed_at: string | null
  horizon_days: number; reviews: ThesisReview[]
}
export interface ThesisRecord { reviews: number; holds: number; weakened: number; broken: number; hold_rate: number | null }
export interface ThesisPage { generated_at: string; record: ThesisRecord; due: Thesis[]; open: Thesis[]; closed: Thesis[] }

export interface Fundamentals {
  source: string; fetched_at: string; as_of: string | null
  market_cap: number | null; pe_trailing: number | null; pe_forward: number | null
  price_to_book: number | null; eps_trailing: number | null; book_value: number | null
  roe: number | null; dividend_yield: number | null; debt_to_equity: number | null
  profit_margin: number | null; revenue_growth: number | null; beta: number | null
}

export interface BriefingItem {
  symbol: string; pinned: boolean; watchlist_id: number | null; name: string; sector: string | null; tier: Tier; score: number
  quote: QuoteOut | null; since: SinceOut | null; reasons: Reason[]
  volume_ratio: number | null; range_position_52w: number | null; high_52w: number | null; low_52w: number | null
  sigma_daily: number | null; streak: number; sparkline: number[]; levels: Level[]; levels_crossed: number[]
  news: { new_count: number; items: NewsOut[] }
  thesis: Thesis | null
  fundamentals: Fundamentals | null
}

export interface Briefing {
  watchlist_id: number; watchlist_version: number; generated_at: string; new_visit: boolean; first_visit: boolean
  market: { is_open: boolean; phase: string; session_date: string; last_close: string; next_open: string }
  data: { active_provider: string; degraded: boolean; note: string | null }
  summary: { attention: number; notable: number; quiet: number; missing: number; headline: string; theses_due: number; theses_open: number; net_change_pct: number | null }
  indices: IndexOut[]
  items: BriefingItem[]
}

export interface PinOut { id: number; symbol: string; position: number }
export interface Board { generated_at: string; items: BriefingItem[] }
export interface SymbolHit { symbol: string; name: string; sector: string | null }
export interface SessionOut { id: number; device_label: string; created_at: string; last_seen_at: string; current: boolean }

export interface IndexOut { symbol: string; name: string; price: number | null; ret_1d: number | null; ret_5d: number | null; ret_20d: number | null; sparkline: number[] }
export interface SectorOut { sector: string; n: number; ret_1d: number | null; ret_5d: number | null; ret_20d: number | null; members: string[] }
export interface MoverOut { symbol: string; name: string; sector: string | null; price: number | null; ret_1d: number | null; ret_5d: number | null; ret_20d: number | null; z_5d: number | null; sparkline: number[] }
export interface MarketPage {
  generated_at: string; session_date: string; is_open: boolean; universe_size: number; scanned: number
  indices: IndexOut[]; sectors: SectorOut[]; gainers_5d: MoverOut[]; losers_5d: MoverOut[]; unusual_5d: MoverOut[]; highs_52w: MoverOut[]; lows_52w: MoverOut[]
}
export interface CompareSeries { symbol: string; name: string; rebased: number[]; last_price: number; return_pct: number; volatility_annual: number; max_drawdown: number; range_position_52w: number | null; avg_volume_20d: number | null; best_day: number | null; worst_day: number | null }
export interface CompareOut { generated_at: string; sessions: number; dates: string[]; series: CompareSeries[]; correlation: (number | null)[][] }
export interface NewsFeedItem { symbol: string; name: string; kind: 'market' | 'following' | 'bigcap'; title: string; url: string; source: string; published_at: string; is_new: boolean }
export interface NewsCounts { all: number; following: number; market: number; new: number }
export interface NewsFeed { generated_at: string; scope: string; symbols: string[]; following: string[]; counts: NewsCounts; items: NewsFeedItem[] }
