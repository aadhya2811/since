export interface User { id: number; email: string }

export interface ItemOut { symbol: string; name: string; position: number; added_at: string }
export interface Watchlist { id: number; name: string; version: number; updated_at: string; items: ItemOut[] }

export interface Freshness { status: 'live' | 'delayed' | 'closed' | 'stale' | 'missing'; label: string; as_of: string | null; fetched_at: string | null; source: string | null; delay_minutes: number | null }
export interface QuoteOut {
  price: number; prev_close: number | null; open: number | null; day_high: number | null; day_low: number | null
  volume: number | null; day_change_pct: number | null; freshness: Freshness
}
export interface SinceOut {
  baseline_price: number; baseline_as_of: string; seen_at: string; seen_label: string
  change_abs: number; change_pct: number; sessions: number; z: number | null
}
export interface Reason { kind: string; severity: 'high' | 'medium' | 'low'; text: string }
export interface Level { id: number; symbol: string; price: number; direction: 'above' | 'below'; note: string | null; created_at: string }
export interface NewsOut { title: string; url: string; source: string; published_at: string; is_new: boolean }

export type Tier = 'attention' | 'notable' | 'quiet'

export interface BriefingItem {
  symbol: string; name: string; sector: string | null; tier: Tier; score: number
  quote: QuoteOut | null; since: SinceOut | null; reasons: Reason[]
  volume_ratio: number | null; range_position_52w: number | null; high_52w: number | null; low_52w: number | null
  sigma_daily: number | null; streak: number; sparkline: number[]; levels: Level[]; levels_crossed: number[]
  news: { new_count: number; items: NewsOut[] }
}

export interface Briefing {
  watchlist_id: number; watchlist_version: number; generated_at: string; new_visit: boolean; first_visit: boolean
  market: { is_open: boolean; phase: string; session_date: string; last_close: string; next_open: string }
  data: { active_provider: string; degraded: boolean; note: string | null }
  summary: { attention: number; notable: number; quiet: number; missing: number; headline: string }
  items: BriefingItem[]
}

export interface SymbolHit { symbol: string; name: string; sector: string | null }
export interface SessionOut { id: number; device_label: string; created_at: string; last_seen_at: string; current: boolean }
