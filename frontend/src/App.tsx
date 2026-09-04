import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, ConflictError, api, auth, newVisit } from './api'
import type { Briefing, BriefingItem, SessionOut, User, Watchlist } from './types'
import { Login } from './components/Login'
import { AddSymbol } from './components/AddSymbol'
import { QuietRow, StockCard } from './components/StockCard'
import { dateTimeIST, timeIST } from './format'

const POLL_MS = 30_000

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  useEffect(() => {
    if (!auth.token()) { setUser(null); return }
    api.me().then(setUser).catch(() => { auth.clear(); setUser(null) })
  }, [])
  if (user === undefined) return <div className="shell"><div className="skeleton" style={{ marginTop: 40 }} /></div>
  if (!user) return <Login onLogin={setUser} />
  return <Main user={user} onLogout={() => { api.logout().catch(() => {}); auth.clear(); setUser(null) }} />
}

function useToast() {
  const [toast, setToast] = useState<{ text: string; warn?: boolean } | null>(null)
  const t = useRef<number>()
  const show = useCallback((text: string, warn = false) => {
    setToast({ text, warn }); window.clearTimeout(t.current)
    t.current = window.setTimeout(() => setToast(null), 4500)
  }, [])
  return { toast, show }
}

function Main({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [lists, setLists] = useState<Watchlist[] | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [briefing, setBriefing] = useState<Briefing | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [showQuiet, setShowQuiet] = useState(false)
  const [sessions, setSessions] = useState<SessionOut[]>([])
  const [error, setError] = useState<string | null>(null)
  const { toast, show } = useToast()

  const active = useMemo(() => lists?.find(l => l.id === activeId) ?? null, [lists, activeId])

  const loadLists = useCallback(async () => {
    const ls = await api.watchlists()
    setLists(ls)
    setActiveId(id => (id && ls.some(l => l.id === id) ? id : ls[0]?.id ?? null))
    return ls
  }, [])

  useEffect(() => { loadLists().catch(e => setError((e as Error).message)); api.sessions().then(setSessions).catch(() => {}) }, [loadLists])

  const refresh = useCallback(async (id: number, quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const b = await api.briefing(id)
      setBriefing(b); setError(null)
      // The briefing carries the watchlist version — keep the tabs in sync if another device changed it.
      setLists(ls => ls && ls.map(l => (l.id === id && l.version !== b.watchlist_version ? { ...l, version: b.watchlist_version } : l)))
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { auth.clear(); location.reload(); return }
      setError((e as Error).message)
    } finally { setLoading(false) }
  }, [])

  // Poll while visible; refetch immediately when the tab regains focus.
  useEffect(() => {
    if (!activeId) return
    setBriefing(null); refresh(activeId)
    const iv = window.setInterval(() => { if (document.visibilityState === 'visible') refresh(activeId, true) }, POLL_MS)
    const onVis = () => { if (document.visibilityState === 'visible') refresh(activeId, true) }
    document.addEventListener('visibilitychange', onVis)
    return () => { window.clearInterval(iv); document.removeEventListener('visibilitychange', onVis) }
  }, [activeId, refresh])

  /** Apply a write; on 409 adopt the server's version and tell the user. */
  async function write(fn: (wl: Watchlist) => Promise<Watchlist>) {
    if (!active) return
    try {
      const updated = await fn(active)
      setLists(ls => ls && ls.map(l => (l.id === updated.id ? updated : l)))
      await refresh(active.id, true)
    } catch (e) {
      if (e instanceof ConflictError) {
        setLists(ls => ls && ls.map(l => (l.id === e.current.id ? e.current : l)))
        show('This watchlist was changed on another device — reloaded the latest version. Try again.', true)
        await refresh(active.id, true)
      } else { show((e as Error).message, true) }
    }
  }

  const addSymbol = (symbol: string) => write(wl => api.addItem(wl.id, symbol, wl.version))
  const removeSymbol = (symbol: string) => write(wl => api.removeItem(wl.id, symbol, wl.version))

  async function ack(symbol: string | null) {
    if (!active) return
    await api.ack(active.id, symbol ? [symbol] : null)
    show(symbol ? `${symbol.replace('.NS', '')} marked as seen — next time you'll see what changed from here.` : 'All marked as seen.')
    await refresh(active.id, true)
  }
  async function rewind(sessions: number) {
    if (!active) return
    await api.rewind(active.id, sessions)
    show(sessions === 0 ? 'Baseline set to the last close.' : `Pretending you last looked ${sessions} session${sessions === 1 ? '' : 's'} ago.`)
    await refresh(active.id, true)
  }
  async function simulateReturn() {
    if (!active) return
    newVisit()
    await refresh(active.id, true)
    show('New visit started: whatever you saw last is now the baseline.')
  }

  const items = briefing?.items ?? []
  const attention = items.filter(i => i.tier === 'attention')
  const notable = items.filter(i => i.tier === 'notable')
  const quiet = items.filter(i => i.tier === 'quiet')
  const existing = new Set(active?.items.map(i => i.symbol) ?? [])

  const cardProps = (it: BriefingItem) => ({
    item: it, expanded: expanded === it.symbol,
    onToggle: () => setExpanded(e => (e === it.symbol ? null : it.symbol)),
    onAck: (s: string) => ack(s), onRemove: removeSymbol,
    onAddLevel: async (s: string, p: number, d: 'above' | 'below', n: string | null) => { await api.addLevel(s, p, d, n); if (active) await refresh(active.id, true) },
    onDeleteLevel: async (id: number) => { await api.deleteLevel(id); if (active) await refresh(active.id, true) },
  })

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><h1>Since<span>.</span></h1><span className="tag">what changed since you last looked</span></div>
        <div className="topbar-right">
          <span className="muted small">{user.email}</span>
          <button className="btn ghost sm" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      {briefing && (
        <div className="strip">
          <span><i className={`dot ${briefing.market.is_open ? 'open' : 'closed'}`} />NSE {briefing.market.is_open ? 'open' : briefing.market.phase === 'pre' ? 'pre-open' : 'closed'}
            {!briefing.market.is_open && <span className="faint"> · last close {dateTimeIST(briefing.market.last_close)} · opens {dateTimeIST(briefing.market.next_open)} IST</span>}
          </span>
          <span><i className={`dot ${briefing.data.degraded ? 'warn' : ''}`} />feed: {briefing.data.active_provider}{briefing.data.active_provider === 'yahoo' ? ' (~15 min delayed)' : ''}</span>
          <span className="faint">updated {timeIST(briefing.generated_at)} IST · refreshes every 30s</span>
          {sessions.length > 1 && <span className="sessions">devices: {sessions.map(s => <span key={s.id} className={s.current ? 'cur' : ''}>{s.device_label}</span>)}</span>}
        </div>
      )}
      {briefing?.data.note && <div className="banner">{briefing.data.note}</div>}
      {error && <div className="banner">{error}</div>}

      {lists && (
        <div className="tabs">
          {lists.map(l => <button key={l.id} className={`tab ${l.id === activeId ? 'active' : ''}`} onClick={() => setActiveId(l.id)}>{l.name} <span className="faint">{l.items.length}</span></button>)}
          <button className="tab" onClick={async () => { const n = prompt('Name the watchlist'); if (n) { const wl = await api.createWatchlist(n); await loadLists(); setActiveId(wl.id) } }}>+ New</button>
          {active && lists.length > 1 && <button className="tab faint" onClick={async () => { if (confirm(`Delete "${active.name}"?`)) { await api.deleteWatchlist(active.id); await loadLists() } }}>delete</button>}
        </div>
      )}

      {lists && lists.length === 0 && (
        <div className="empty">
          <h3>No watchlist yet</h3>
          <p>Start with a sample of 12 NSE stocks (with a few days of history so you can see the briefing work), or build your own.</p>
          <button className="btn primary" onClick={async () => { const wl = await api.createSample(); await loadLists(); setActiveId(wl.id) }}>Create sample watchlist</button>{' '}
          <button className="btn" onClick={async () => { const wl = await api.createWatchlist('My watchlist'); await loadLists(); setActiveId(wl.id) }}>Start empty</button>
        </div>
      )}

      {active && (
        <>
          <div className="headline">
            <h2>{briefing ? briefing.summary.headline : loading ? 'Reading the market…' : ''}</h2>
            {briefing && briefing.new_visit && items.length > 0 && <div className="sub">Welcome back. Changes below are measured from what <b>you</b> last saw, not from yesterday's close.</div>}
          </div>

          <div style={{ marginTop: 14 }}><AddSymbol onAdd={addSymbol} existing={existing} /></div>

          {!briefing && loading && <div className="list" style={{ marginTop: 20 }}><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>}

          {briefing && items.length === 0 && <div className="empty"><h3>Empty watchlist</h3><p>Add a few symbols above.</p></div>}

          {attention.length > 0 && (
            <section className="section attention">
              <div className="section-h"><h3>Needs your attention</h3><span className="count">{attention.length}</span><span className="spacer" /><button className="btn ghost sm" onClick={() => ack(null)}>Mark all seen</button></div>
              <div className="list">{attention.map(it => <StockCard key={it.symbol} {...cardProps(it)} />)}</div>
            </section>
          )}
          {notable.length > 0 && (
            <section className="section notable">
              <div className="section-h"><h3>Worth a glance</h3><span className="count">{notable.length}</span></div>
              <div className="list">{notable.map(it => <StockCard key={it.symbol} {...cardProps(it)} />)}</div>
            </section>
          )}
          {quiet.length > 0 && (
            <section className="section">
              <div className="section-h"><h3>Quiet</h3><span className="count">{quiet.length}</span><span className="spacer" />
                <button className="btn ghost sm" onClick={() => setShowQuiet(s => !s)}>{showQuiet ? 'Collapse' : 'Expand'}</button></div>
              <div className="list">
                {quiet.map(it => (showQuiet || expanded === it.symbol)
                  ? <StockCard key={it.symbol} {...cardProps(it)} />
                  : <QuietRow key={it.symbol} item={it} onClick={() => setExpanded(it.symbol)} />)}
              </div>
            </section>
          )}

          {briefing && items.length > 0 && (
            <div className="demo">
              <span className="grow"><b>Try it:</b> the briefing diffs against what <em>you</em> last saw. Pretend you last checked…</span>
              {[1, 3, 5, 10].map(n => <button key={n} className="btn sm" onClick={() => rewind(n)}>{n} session{n === 1 ? '' : 's'} ago</button>)}
              <button className="btn sm" onClick={() => rewind(0)}>at last close</button>
              <span className="faint">·</span>
              <button className="btn ghost sm" onClick={simulateReturn} title="Ends the current visit: what you're seeing now becomes the new baseline">Simulate leaving &amp; coming back</button>
            </div>
          )}
        </>
      )}

      {toast && <div className={`toast ${toast.warn ? 'warn' : ''}`}>{toast.text}</div>}
    </div>
  )
}
