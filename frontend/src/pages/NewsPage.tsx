import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { NewsFeed } from '../types'
import { ago } from '../format'

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')

/** Every headline for every stock you follow — the ones you haven't seen first. */
export function NewsPage() {
  const [feed, setFeed] = useState<NewsFeed | null>(null)
  const [filter, setFilter] = useState<string | null>(null)
  const [days, setDays] = useState(7)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { api.news(days).then(setFeed).catch(e => setErr((e as Error).message)) }, [days])

  const items = useMemo(() => (feed?.items ?? []).filter(i => !filter || i.symbol === filter), [feed, filter])
  const fresh = items.filter(i => i.is_new)
  const older = items.filter(i => !i.is_new)
  const counts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const i of feed?.items ?? []) if (i.is_new) m[i.symbol] = (m[i.symbol] ?? 0) + 1
    return m
  }, [feed])

  if (err) return <div className="banner">{err}</div>
  if (!feed) return <div className="list" style={{ marginTop: 20 }}><div className="skeleton" /><div className="skeleton" /></div>

  return (
    <>
      <div className="headline">
        <h2>{fresh.length === 0 ? 'No new headlines since you looked.' : `${fresh.length} new headline${fresh.length === 1 ? '' : 's'} since you looked.`}</h2>
        <div className="sub">Across every stock you follow · Google News · headlines are context, not signals.</div>
      </div>

      <div className="tabs" style={{ marginTop: 12 }}>
        <button className={`tab ${filter === null ? 'active' : ''}`} onClick={() => setFilter(null)}>All <span className="faint">{feed.items.length}</span></button>
        {feed.symbols.map(s => (
          <button key={s} className={`tab ${filter === s ? 'active' : ''}`} onClick={() => setFilter(s)}>
            {ticker(s)} {counts[s] ? <span className="badge new" style={{ marginLeft: 4 }}>{counts[s]}</span> : null}
          </button>
        ))}
        <span className="spacer" style={{ flex: 1 }} />
        <select className="input" style={{ width: 'auto', padding: '6px 10px' }} value={days} onChange={e => setDays(Number(e.target.value))}>
          <option value={3}>last 3 days</option><option value={7}>last 7 days</option><option value={14}>last 14 days</option><option value={30}>last 30 days</option>
        </select>
      </div>

      {fresh.length > 0 && (
        <section className="section">
          <div className="section-h"><h3>New since you looked</h3><span className="count">{fresh.length}</span></div>
          <div className="newsfeed">{fresh.map((n, i) => <NewsRow key={i} n={n} />)}</div>
        </section>
      )}
      <section className="section">
        <div className="section-h"><h3>{fresh.length ? 'Earlier' : 'Recent'}</h3><span className="count">{older.length}</span></div>
        {older.length === 0 ? <div className="faint small">Nothing else in this window.</div> : <div className="newsfeed">{older.map((n, i) => <NewsRow key={i} n={n} dim />)}</div>}
      </section>
    </>
  )
}

function NewsRow({ n, dim }: { n: NewsFeed['items'][number]; dim?: boolean }) {
  return (
    <a className={`newsrow ${dim ? 'dim' : ''}`} href={n.url} target="_blank" rel="noreferrer">
      <span className="nr-sym">{ticker(n.symbol)}</span>
      <span className="nr-title">{n.title}</span>
      <span className="nr-meta">{n.source} · {ago(n.published_at)}</span>
    </a>
  )
}
