import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { Thesis, ThesisPage } from '../types'
import { ReviewHistory, ThesisBlock } from '../components/ThesisBlock'
import { dateIST, inr, pct, sign } from '../format'

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')

/** Analyst memory, gathered in one place.
 *
 * The briefing asks "what changed?". This page asks the harder question:
 * "were you right, and how often?". The record at the top is the number
 * almost nobody keeps on themselves — not P&L, which conflates being right
 * with being lucky, but how often the *reason* survived. */
export function MemoryPage() {
  const [d, setD] = useState<ThesisPage | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(async () => {
    try { setD(await api.theses()) } catch (e) { setErr((e as Error).message) }
  }, [])
  useEffect(() => { load() }, [load])

  if (err) return <div className="banner">{err}</div>
  if (!d) return <div className="list" style={{ marginTop: 20 }}><div className="skeleton" /><div className="skeleton" /></div>

  const total = d.due.length + d.open.length + d.closed.length
  const r = d.record

  return (
    <>
      <div className="headline">
        <h2>{d.due.length > 0
          ? `${d.due.length} reason${d.due.length === 1 ? '' : 's'} worth re-reading.`
          : total === 0 ? 'Analyst memory.' : 'Nothing needs re-reading right now.'}</h2>
        <div className="sub">
          Everyone remembers the price they bought at. Almost nobody remembers <em>why</em> — which is
          the only way to tell a broken thesis from a bad week. Write the reason down; Since asks you
          about it when the market gives it a reason to.
        </div>
      </div>

      {r.reviews > 0 && (
        <div className="record">
          <div className="rec-cell"><div className="cs-k">Your record</div>
            <div className="cs-v num">{r.hold_rate != null ? `${Math.round(r.hold_rate * 100)}%` : '—'}</div>
            <div className="cs-sub faint">of your reasons held up</div></div>
          <div className="rec-bar">
            <div className="seg holds" style={{ flex: r.holds || 0 }} title={`${r.holds} held`} />
            <div className="seg weakened" style={{ flex: r.weakened || 0 }} title={`${r.weakened} weakened`} />
            <div className="seg broken" style={{ flex: r.broken || 0 }} title={`${r.broken} broke`} />
          </div>
          <div className="rec-legend">
            <span><i className="sw holds" />{r.holds} held</span>
            <span><i className="sw weakened" />{r.weakened} weakened</span>
            <span><i className="sw broken" />{r.broken} broke</span>
            <span className="faint">across {r.reviews} review{r.reviews === 1 ? '' : 's'}</span>
          </div>
        </div>
      )}

      {total === 0 && (
        <div className="hero" style={{ marginTop: 18 }}>
          <div className="eyebrow">Nothing on file yet</div>
          <h2>Write down why,<br />not just what.</h2>
          <p>Open any stock on your briefing and use <b>Why this one?</b>. Takes one sentence. In three
             months it's the most valuable thing in this app.</p>
        </div>
      )}

      {d.due.length > 0 && (
        <section className="section attention" style={{ marginTop: 18 }}>
          <div className="section-h"><h3>Asking now</h3><span className="count">{d.due.length}</span></div>
          <div className="list">{d.due.map(t => <MemoryCard key={t.id} t={t} onChanged={load} open />)}</div>
        </section>
      )}
      {d.open.length > 0 && (
        <section className="section" style={{ marginTop: 18 }}>
          <div className="section-h"><h3>Open reasons</h3><span className="count">{d.open.length}</span></div>
          <div className="list">{d.open.map(t => <MemoryCard key={t.id} t={t} onChanged={load} />)}</div>
        </section>
      )}
      {d.closed.length > 0 && (
        <section className="section" style={{ marginTop: 18 }}>
          <div className="section-h"><h3>Closed</h3><span className="count">{d.closed.length}</span>
            <span className="spacer" /><span className="faint small">Kept on purpose — a thesis that broke is the most useful one to re-read.</span></div>
          <div className="list">{d.closed.map(t => <ClosedCard key={t.id} t={t} />)}</div>
        </section>
      )}
    </>
  )
}

function MemoryCard({ t, onChanged, open = false }: { t: Thesis; onChanged: () => Promise<void>; open?: boolean }) {
  const [expanded, setExpanded] = useState(open)
  return (
    <div className={`card memory ${t.review_due ? 'attention' : 'quiet'}`}>
      <div className="card-main" onClick={() => setExpanded(e => !e)}>
        <div className="sym">
          <div className="ticker">{ticker(t.symbol)}
            {t.review_due && <span className="badge new">asking</span>}
            {t.review_count > 0 && <span className="badge">{t.review_count} review{t.review_count === 1 ? '' : 's'}</span>}
          </div>
          <div className="name">{t.name} · written {t.age_label}</div>
        </div>
        <div className="thesis-inline muted">{expanded ? <span className="faint">{t.review_due ? 'Asking about this one below.' : 'Open — nothing needs re-reading yet.'}</span> : t.text}</div>
        <div className="sincecol num">
          <div className={`big ${sign(t.change_pct)}`}>{pct(t.change_pct)}</div>
          <div className="lbl">since you wrote it</div>
        </div>
      </div>
      {expanded && <div className="detail one"><ThesisBlock symbol={t.symbol} thesis={t} onChanged={onChanged} /></div>}
    </div>
  )
}

function ClosedCard({ t }: { t: Thesis }) {
  return (
    <div className="card memory quiet closed">
      <div className="card-main">
        <div className="sym">
          <div className="ticker">{ticker(t.symbol)}<span className="badge">closed {dateIST(t.reviews[0]?.created_at ?? t.anchored_at)}</span></div>
          <div className="name">{t.name} · held {t.age_label.replace(' ago', '')}</div>
        </div>
        <div className="thesis-inline muted">{t.text}</div>
        <div className="sincecol num">
          <div className="lbl">{inr(t.anchor_price)} → {inr(t.price)}</div>
        </div>
      </div>
      {t.reviews.length > 0 && <div className="detail one"><ReviewHistory reviews={t.reviews} /></div>}
    </div>
  )
}
