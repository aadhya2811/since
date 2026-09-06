/* Thin API client. Owns three cross-cutting concerns:
 *  - the bearer token (localStorage, survives reloads on this device)
 *  - the visit id (sessionStorage: a new tab / reopened browser = "came back")
 *  - optimistic concurrency: If-Match on writes, ConflictError on 409
 */
import type { Board, Briefing, CompareOut, Level, MarketPage, NewsFeed, PinOut, SessionOut, SymbolHit, Thesis, ThesisPage, User, Verdict, Watchlist } from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}
export class ConflictError extends ApiError {
  constructor(public current: Watchlist) { super(409, 'Watchlist changed on another device') }
}

function safeGet(store: Storage, k: string): string | null { try { return store.getItem(k) } catch { return null } }
function safeSet(store: Storage, k: string, v: string) { try { store.setItem(k, v) } catch { /* private mode */ } }
function safeDel(store: Storage, k: string) { try { store.removeItem(k) } catch { /* ignore */ } }

export const auth = {
  token: () => safeGet(localStorage, 'since.token'),
  set: (t: string) => safeSet(localStorage, 'since.token', t),
  clear: () => safeDel(localStorage, 'since.token'),
}

export function visitId(): string {
  let v = safeGet(sessionStorage, 'since.visit')
  if (!v) {
    v = Math.random().toString(36).slice(2) + Date.now().toString(36)
    safeSet(sessionStorage, 'since.visit', v)
  }
  return v
}
export function newVisit() { safeDel(sessionStorage, 'since.visit'); return visitId() }

async function req<T>(method: string, path: string, body?: unknown, extra: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', 'X-Visit-Id': visitId(), ...extra }
  const t = auth.token()
  if (t) headers.Authorization = `Bearer ${t}`
  let res: Response
  try {
    res = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, 'Cannot reach the server')
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (res.status === 409 && data.current) throw new ConflictError(data.current)
  if (!res.ok) throw new ApiError(res.status, data.detail ?? res.statusText)
  return data as T
}

export const api = {
  requestCode: (email: string) => req<{ dev_code: string | null; message: string; delivery: 'email' | 'on-screen' }>('POST', '/api/auth/request-code', { email }),
  verify: (email: string, code: string, device_label: string) => req<{ token: string; user: User }>('POST', '/api/auth/verify', { email, code, device_label }),
  me: () => req<User>('GET', '/api/auth/me'),
  sessions: () => req<SessionOut[]>('GET', '/api/auth/sessions'),
  logout: () => req<void>('POST', '/api/auth/logout'),

  watchlists: () => req<Watchlist[]>('GET', '/api/watchlists'),
  createWatchlist: (name: string) => req<Watchlist>('POST', '/api/watchlists', { name }),
  createSample: () => req<Watchlist>('POST', '/api/watchlists/sample'),
  deleteWatchlist: (id: number) => req<void>('DELETE', `/api/watchlists/${id}`),
  addItem: (id: number, symbol: string, version: number) => req<Watchlist>('POST', `/api/watchlists/${id}/items`, { symbol }, { 'If-Match': String(version) }),
  removeItem: (id: number, symbol: string, version: number) => req<Watchlist>('DELETE', `/api/watchlists/${id}/items/${encodeURIComponent(symbol)}`, undefined, { 'If-Match': String(version) }),

  briefing: (id: number) => req<Briefing>('GET', `/api/watchlists/${id}/briefing`),
  ack: (id: number, symbols: string[] | null) => req<void>('POST', `/api/watchlists/${id}/ack`, { symbols }),
  rewind: (id: number, sessions: number) => req<{ rewound: number }>('POST', `/api/watchlists/${id}/demo/rewind`, { sessions }),

  board: () => req<Board>('GET', '/api/pins/board'),
  pin: (symbol: string) => req<PinOut[]>('POST', '/api/pins', { symbol }),
  unpin: (symbol: string) => req<PinOut[]>('DELETE', `/api/pins/${encodeURIComponent(symbol)}`),

  market: () => req<MarketPage>('GET', '/api/market'),
  compare: (symbols: string[], sessions: number) => req<CompareOut>('GET', `/api/compare?symbols=${encodeURIComponent(symbols.join(','))}&sessions=${sessions}`),
  news: (days = 7, scope: 'all' | 'following' | 'market' = 'all') => req<NewsFeed>('GET', `/api/news?days=${days}&scope=${scope}`),

  theses: () => req<ThesisPage>('GET', '/api/thesis'),
  createThesis: (symbol: string, text: string, horizon_days: number) => req<Thesis>('POST', '/api/thesis', { symbol, text, horizon_days }),
  editThesis: (id: number, body: { text?: string; horizon_days?: number }) => req<Thesis>('PATCH', `/api/thesis/${id}`, body),
  deleteThesis: (id: number) => req<void>('DELETE', `/api/thesis/${id}`),
  reviewThesis: (id: number, verdict: Verdict, note: string | null) => req<Thesis>('POST', `/api/thesis/${id}/review`, { verdict, note }),
  rewindThesis: (id: number, sessions: number) => req<Thesis>('POST', `/api/thesis/${id}/demo/rewind?sessions=${sessions}`),
  snoozeThesis: (id: number, days = 7) => req<Thesis>('POST', `/api/thesis/${id}/snooze?days=${days}`),

  addLevel: (symbol: string, price: number, direction: 'above' | 'below', note: string | null) => req<Level>('POST', '/api/levels', { symbol, price, direction, note }),
  deleteLevel: (id: number) => req<void>('DELETE', `/api/levels/${id}`),
  search: (q: string) => req<SymbolHit[]>('GET', `/api/symbols/search?q=${encodeURIComponent(q)}`),
}

export function deviceLabel(): string {
  const ua = navigator.userAgent
  const os = /Windows/.test(ua) ? 'Windows' : /Mac/.test(ua) ? 'Mac' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Linux/.test(ua) ? 'Linux' : 'device'
  const br = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser'
  return `${br} on ${os}`
}
