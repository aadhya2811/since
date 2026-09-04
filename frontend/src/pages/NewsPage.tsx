import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { NewsFeed, NewsFeedItem } from '../types'
import { ago } from '../format'

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')
type Scope = 'all' | 'following' | 'market'

/** Publishers get a stable colour from their name, so the same masthead always
 *  looks the same. Google News RSS carries no images — a monogram plus real
 *  typographic hierarchy does the work an image would. */
const PUB_HUES = [212, 258, 158, 32, 340, 190, 280, 12]
function pubStyle(source: string) {
  let h = 0
  for (let i = 0; i < source.length; i++) h = (h * 31 + source.charCodeAt(i)) >>> 0
  const hue = PUB_HUES[h % PUB_HUES.length]
  return { background: `hsl(${hue} 62% 22%)`, color: `hsl(${hue} 80% 78%)`, borderColor: `hsl(${hue} 55% 38%)` }
}
const monogram = (source: string) => source.split(/\s+/).filter(w => /[A-Za-z]/.test(w)).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '·'

/** Topic pseudo-symbols read as a section, not a ticker. */
const isTopic = (s: string) => s.startsWith('^')

export function NewsPage() {
  const [feed, setFeed] = useState<NewsFeed | null>(null)
  const [scope, setScope] = useState<Scope>('all')
  const [symbol, setSymbol] = useState<string | null>(null)
  const [days, setDays] = useState(7)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true); setSymbol(null)
    api.news(days, scope).then(f => { setFeed(f); setErr(null) }).catch(e => setErr((e as Error).message)).finally(() => setLoading(false))
  }, [days, scope])

  const items = useMemo(() => (feed?.items ?? []).filter(i => !symbol || i.symbol === symbol), [feed, symbol])
  const perSymbol = useMemo(() => {
    const m: Record<string, { total: number; fresh: number }> = {}
    for (const i of feed?.items ?? []) {
      m[i.symbol] ??= { total: 0, fresh: 0 }
      m[i.symbol].total++
      if (i.is_new) m[i.symbol].fresh++
    }
    return m
  }, [feed])

  if (err) return <div className="banner">{err}</div>
  if (!feed || loading) return (
    <div style={{ marginTop: 26 }}><div className="skeleton" style={{ height: 150 }} /><div className="cards" style={{ marginTop: 10 }}>{[0, 1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 120 }} />)}</div></div>
  )

  const [lead, ...rest] = items
  const fresh = rest.filter(i => i.is_new)
  const older = rest.filter(i => !i.is_new)
  const c = feed.counts

  return (
    <>
      <div className="headline">
        <h2>{c.new > 0 ? `${c.new} new headline${c.new === 1 ? '' : 's'} since you looked.` : scope === 'following' ? 'Nothing new on your stocks.' : 'Today in the market.'}</h2>
        <div className="sub">
          {scope === 'following' ? 'Only the companies on your watchlists.' : scope === 'market' ? 'Indices, policy, flows, IPOs and the index heavyweights.' : 'The market, your stocks, and the names that move the index.'}
          {' '}Headlines are context — Since doesn't score or rate them.
        </div>
      </div>

      <div className="newsbar">
        <div className="seg big">
          <button className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>Everything <span className="n">{c.all}</span></button>
          <button className={scope === 'following' ? 'on' : ''} onClick={() => setScope('following')}>My stocks <span className="n">{c.following}</span></button>
          <button className={scope === 'market' ? 'on' : ''} onClick={() => setScope('market')}>Market <span className="n">{c.market}</span></button>
        </div>
        <span style={{ flex: 1 }} />
        <div className="seg">{[3, 7, 14].map(d => <button key={d} className={days === d ? 'on' : ''} onClick={() => setDays(d)}>{d}d</button>)}</div>
      </div>

      {feed.symbols.length > 1 && (
        <div className="chiprow">
          <button className={`fchip ${symbol === null ? 'on' : ''}`} onClick={() => setSymbol(null)}>All</button>
          {feed.symbols.map(s => (
            <button key={s} className={`fchip ${symbol === s ? 'on' : ''} ${isTopic(s) ? 'topic' : ''}`} onClick={() => setSymbol(s === symbol ? null : s)}>
              {isTopic(s) ? (feed.items.find(i => i.symbol === s)?.name ?? ticker(s)) : ticker(s)}
              {perSymbol[s]?.fresh ? <em>{perSymbol[s].fresh}</em> : null}
            </button>
          ))}
        </div>
      )}

      {items.length === 0 && (
        <div className="empty" style={{ marginTop: 18 }}>
          <h3>No headlines here yet</h3>
          <p>{scope === 'following' ? 'Add a few stocks to your watchlist, or switch to Market.' : 'Headlines arrive within a minute or two of the app starting.'}</p>
        </div>
      )}

      {lead && <LeadStory n={lead} />}

      {fresh.length > 0 && (
        <section className="section">
          <div className="section-h"><h3>New since you looked</h3><span className="count">{fresh.length}</span></div>
          <div className="cards">{fresh.map((n, i) => <Card key={i} n={n} />)}</div>
        </section>
      )}
      {older.length > 0 && (
        <section className="section">
          <div className="section-h"><h3>{fresh.length ? 'Earlier' : 'Recent'}</h3><span className="count">{older.length}</span></div>
          <div className="cards">{older.map((n, i) => <Card key={i} n={n} dim />)}</div>
        </section>
      )}
    </>
  )
}

function Tag({ n }: { n: NewsFeedItem }) {
  if (n.kind === 'market') return <span className="ntag market">{n.name}</span>
  return <span className={`ntag ${n.kind}`}>{ticker(n.symbol)}{n.kind === 'bigcap' && <i> · index heavyweight</i>}</span>
}

function LeadStory({ n }: { n: NewsFeedItem }) {
  return (
    <a className={`lead ${n.is_new ? 'fresh' : ''}`} href={n.url} target="_blank" rel="noreferrer">
      <div className="lead-meta">
        <span className="pub lg" style={pubStyle(n.source)}>{monogram(n.source)}</span>
        <span className="pub-name">{n.source}</span>
        <span className="faint">· {ago(n.published_at)}</span>
        {n.is_new && <span className="badge new">new</span>}
      </div>
      <h3 className="lead-title">{n.title}</h3>
      <div className="lead-foot"><Tag n={n} /><span className="readmore">Read →</span></div>
    </a>
  )
}

function Card({ n, dim }: { n: NewsFeedItem; dim?: boolean }) {
  return (
    <a className={`ncard ${dim ? 'dim' : ''} ${n.is_new ? 'fresh' : ''}`} href={n.url} target="_blank" rel="noreferrer">
      <div className="nc-top"><Tag n={n} />{n.is_new && <span className="dot-new" title="New since you last looked" />}</div>
      <h4 className="nc-title">{n.title}</h4>
      <div className="nc-foot">
        <span className="pub" style={pubStyle(n.source)}>{monogram(n.source)}</span>
        <span className="pub-name">{n.source}</span>
        <span className="faint">· {ago(n.published_at)}</span>
      </div>
    </a>
  )
}
