import { useState } from 'react'
import type { BriefingItem, Reason } from '../types'
import { ago, compact, dateTimeIST, inr, pct, sign } from '../format'
import { Sparkline } from './Sparkline'

interface Props {
  item: BriefingItem
  expanded: boolean
  onToggle: () => void
  onAck: (symbol: string) => Promise<void>
  onRemove: (symbol: string) => Promise<void>
  onAddLevel: (symbol: string, price: number, direction: 'above' | 'below', note: string | null) => Promise<void>
  onDeleteLevel: (id: number) => Promise<void>
}

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')

function Chip({ r, dir }: { r: Reason; dir: 'up' | 'down' | 'flat' }) {
  const cls = ['chip', r.kind === 'error' ? 'error' : r.severity, r.kind === 'news' ? 'news' : '', r.kind === 'level' ? 'level' : '', dir === 'up' && r.kind === 'move' ? 'pos' : ''].join(' ')
  return <span className={cls} title={r.text}>{r.text}</span>
}

export function StockCard(p: Props) {
  const { item } = p
  const q = item.quote, s = item.since
  const dir = sign(s?.change_pct)
  const [lvPrice, setLvPrice] = useState('')
  const [lvDir, setLvDir] = useState<'above' | 'below'>('below')
  const [lvNote, setLvNote] = useState('')
  const [busy, setBusy] = useState(false)

  const primary = item.reasons.filter(r => r.kind !== 'info' || item.reasons.length === 1)

  return (
    <div className={`card ${item.tier} ${dir === 'up' ? 'pos' : ''}`}>
      <div className="card-main" onClick={p.onToggle}>
        <div className="sym">
          <div className="ticker">
            {ticker(item.symbol)}
            {q && <span className={`badge ${q.freshness.status}`}>{q.freshness.label}</span>}
            {item.news.new_count > 0 && <span className="badge new">{item.news.new_count} new {item.news.new_count === 1 ? 'headline' : 'headlines'}</span>}
          </div>
          <div className="name">{item.name}{item.sector ? ` · ${item.sector}` : ''}</div>
        </div>
        <div className="price num">
          <div className="p">{inr(q?.price)}</div>
          <div className={`d ${sign(q?.day_change_pct)}`}>{pct(q?.day_change_pct)} today</div>
        </div>
        <div className="spark">
          <Sparkline data={item.sparkline} baseline={s?.baseline_price ?? null} />
        </div>
        <div className="sincecol num">
          {s ? (
            <>
              <div className={`big ${dir}`}>{pct(s.change_pct)}</div>
              <div className="lbl">since {s.seen_label}{s.z != null && Math.abs(s.z) >= 0.05 ? ` · ${Math.abs(s.z).toFixed(1)}σ` : ''}</div>
            </>
          ) : <div className="lbl">—</div>}
        </div>
      </div>

      {primary.length > 0 && (
        <div className="chips" onClick={p.onToggle}>
          {primary.map((r, i) => <Chip key={i} r={r} dir={dir} />)}
        </div>
      )}

      {p.expanded && q && s && (
        <div className="detail" onClick={e => e.stopPropagation()}>
          <div>
            <h4>Since you looked</h4>
            <div className="kv">
              <span className="k">You last saw</span><span className="num">{inr(s.baseline_price)} <span className="faint">({dateTimeIST(s.baseline_as_of)} IST)</span></span>
              <span className="k">Now</span><span className="num">{inr(q.price)} <span className={dir}>{pct(s.change_pct)}</span> <span className="faint">over {s.sessions} session{s.sessions === 1 ? '' : 's'}</span></span>
              <span className="k">How unusual</span><span>{s.z != null ? <><span className="num">{Math.abs(s.z).toFixed(2)}σ</span> <span className="faint">— this stock typically moves {pct(item.sigma_daily, false)}/day</span></> : <span className="faint">no new prints</span>}</span>
              <span className="k">Volume</span><span className="num">{compact(q.volume)} {item.volume_ratio != null && <span className={item.volume_ratio >= 2 ? 'muted' : 'faint'}>({item.volume_ratio.toFixed(1)}× normal)</span>}</span>
              <span className="k">Day range</span><span className="num">{inr(q.day_low)} – {inr(q.day_high)} <span className="faint">open {inr(q.open)}, prev close {inr(q.prev_close)}</span></span>
              <span className="k">Data</span><span className="faint">{q.freshness.label} · source: {q.freshness.source} · fetched {q.freshness.fetched_at ? ago(q.freshness.fetched_at) : '—'}</span>
            </div>
            {item.high_52w != null && item.low_52w != null && (
              <>
                <h4 style={{ marginTop: 16 }}>52-week range</h4>
                <div className="range"><div className="fill" style={{ width: `${(item.range_position_52w ?? 0) * 100}%` }} /><div className="pin" style={{ left: `${(item.range_position_52w ?? 0) * 100}%` }} /></div>
                <div className="range-l"><span className="num">{inr(item.low_52w)}</span><span className="num">{inr(item.high_52w)}</span></div>
              </>
            )}
          </div>

          <div>
            <h4>News {item.news.new_count > 0 && <span className="badge new" style={{ marginLeft: 6 }}>{item.news.new_count} since you looked</span>}</h4>
            {item.news.items.length === 0 ? <div className="faint small">No recent headlines.</div> : (
              <ul className="news-list">
                {item.news.items.map((n, i) => (
                  <li key={i} style={{ opacity: n.is_new ? 1 : 0.6 }}>
                    <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
                    <div className="meta">{n.source} · {ago(n.published_at)}{n.is_new ? ' · new' : ''}</div>
                  </li>
                ))}
              </ul>
            )}

            <h4 style={{ marginTop: 16 }}>Your levels</h4>
            <div className="levels">
              {item.levels.length === 0 && <div className="faint small">None yet. Set a price you care about and you'll be told when it's crossed.</div>}
              {item.levels.map(l => (
                <div key={l.id} className={`level-row ${item.levels_crossed.includes(l.id) ? 'hit' : ''}`}>
                  <span className="num">{l.direction === 'below' ? '↓' : '↑'} {inr(l.price)}</span>
                  {l.note && <span className="muted">— {l.note}</span>}
                  {item.levels_crossed.includes(l.id) && <span className="badge new">crossed</span>}
                  <span style={{ flex: 1 }} />
                  <button className="btn ghost sm" onClick={() => p.onDeleteLevel(l.id)}>remove</button>
                </div>
              ))}
              <form className="level-form" onSubmit={async e => {
                e.preventDefault(); const v = parseFloat(lvPrice); if (!v) return
                setBusy(true); try { await p.onAddLevel(item.symbol, v, lvDir, lvNote.trim() || null); setLvPrice(''); setLvNote('') } finally { setBusy(false) }
              }}>
                <select value={lvDir} onChange={e => setLvDir(e.target.value as 'above' | 'below')}><option value="below">Falls below</option><option value="above">Rises above</option></select>
                <input className="input" placeholder="price" inputMode="decimal" value={lvPrice} onChange={e => setLvPrice(e.target.value)} />
                <input className="input" placeholder="note (optional)" value={lvNote} onChange={e => setLvNote(e.target.value)} />
                <button className="btn sm" disabled={busy}>Set level</button>
              </form>
            </div>
          </div>

          <div className="detail-actions">
            <button className="btn ghost sm danger" onClick={() => p.onRemove(item.symbol)}>Remove from watchlist</button>
            <button className="btn sm" onClick={() => p.onAck(item.symbol)} title="Reset the baseline to now: next time, you'll see what changed from here">Seen it ✓</button>
          </div>
        </div>
      )}
    </div>
  )
}

export function QuietRow({ item, onClick }: { item: BriefingItem; onClick: () => void }) {
  const s = item.since, q = item.quote
  const move = item.reasons.find(r => r.kind === 'move')
  const err = item.reasons.find(r => r.kind === 'error')
  return (
    <div className="quiet-row" onClick={onClick}>
      <span className="t">{ticker(item.symbol)}</span>
      <span className={`n ${err ? 'error' : ''}`}>{err ? err.text : move ? move.text : item.reasons[0]?.text ?? item.name}</span>
      <span className="spark"><Sparkline data={item.sparkline} width={70} height={22} baseline={s?.baseline_price ?? null} /></span>
      <span className="num muted" style={{ width: 80, textAlign: 'right' }}>{inr(q?.price)}</span>
      <span className={`num ${sign(s?.change_pct)}`} style={{ width: 60, textAlign: 'right' }}>{pct(s?.change_pct)}</span>
    </div>
  )
}
