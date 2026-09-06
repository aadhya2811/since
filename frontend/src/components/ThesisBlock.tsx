import { useState } from 'react'
import { api } from '../api'
import type { Thesis, Verdict } from '../types'
import { dateIST, inr, pct, sign } from '../format'

/** Analyst memory, inline on a stock card.
 *
 * Three states, and only three: you haven't written a reason, you have one and
 * nothing has happened, or something happened and we're asking. The prompt
 * deliberately shows your own words *above* the price move, because the whole
 * point is to re-read the reason before you look at the number. */
export function ThesisBlock({ symbol, thesis, onChanged }: {
  symbol: string
  thesis: Thesis | null
  onChanged: () => Promise<void> | void
}) {
  const [writing, setWriting] = useState(false)
  const [text, setText] = useState('')
  const [horizon, setHorizon] = useState(90)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await fn(); await onChanged(); setWriting(false); setText('') }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  if (!thesis) {
    return (
      <div className="thesis empty">
        <h4>Why this one?</h4>
        {!writing ? (
          <>
            <p className="faint small">
              Write the reason you got interested, in your own words. Since timestamps it and shows it
              back to you when something happens that's worth re-reading it against.
            </p>
            <button className="btn sm" onClick={() => setWriting(true)}>Write my reason</button>
          </>
        ) : (
          <form onSubmit={e => { e.preventDefault(); if (text.trim().length >= 3) run(() => api.createThesis(symbol, text.trim(), horizon)) }}>
            <textarea className="input ta" rows={3} autoFocus value={text} onChange={e => setText(e.target.value)}
                      placeholder="e.g. Order book is 3 years deep and nobody is pricing the defence contracts yet." />
            <div className="thesis-form-row">
              <label className="faint small">Ask me again within
                <select value={horizon} onChange={e => setHorizon(Number(e.target.value))}>
                  <option value={30}>1 month</option><option value={90}>3 months</option>
                  <option value={180}>6 months</option><option value={365}>1 year</option>
                </select>
              </label>
              <span style={{ flex: 1 }} />
              <button type="button" className="btn ghost sm" onClick={() => setWriting(false)}>Cancel</button>
              <button className="btn sm primary" disabled={busy || text.trim().length < 3}>Save reason</button>
            </div>
            {err && <div className="err small">{err}</div>}
          </form>
        )}
      </div>
    )
  }

  return (
    <div className={`thesis ${thesis.review_due ? 'due' : ''}`}>
      <h4>
        Your reason
        <span className="faint" style={{ fontWeight: 400, letterSpacing: 0, textTransform: 'none' }}>
          {' · written '}{thesis.age_label}
          {thesis.review_count > 0 && `, reviewed ${thesis.review_count}×`}
        </span>
      </h4>
      <blockquote className="thesis-text">{thesis.text}</blockquote>

      <div className="thesis-since">
        <span className="faint small">Since you wrote it:</span>
        <span className={`num ${sign(thesis.change_pct)}`}>{pct(thesis.change_pct)}</span>
        <span className="faint small">
          {inr(thesis.anchor_price)} → {inr(thesis.price)}
          {thesis.sessions > 0 && ` over ${thesis.sessions} session${thesis.sessions === 1 ? '' : 's'}`}
          {thesis.z != null && Math.abs(thesis.z) >= 0.05 && ` · ${Math.abs(thesis.z).toFixed(1)}σ`}
        </span>
      </div>

      {thesis.review_due ? (
        <ReviewPrompt thesis={thesis} busy={busy} err={err}
                      onAnswer={(v, note) => run(() => api.reviewThesis(thesis.id, v, note))}
                      onSnooze={() => run(() => api.snoozeThesis(thesis.id))} />
      ) : (
        <div className="thesis-actions">
          <span className="faint small">
            Nothing has happened that's worth re-reading this against yet.
            {thesis.last_verdict && ` Last review: ${thesis.last_verdict}.`}
          </span>
          <span style={{ flex: 1 }} />
          <button className="btn ghost sm" onClick={() => run(() => api.reviewThesis(thesis.id, 'holds', null))}>Still holds ✓</button>
          <button className="btn ghost sm danger" onClick={() => { if (confirm('Delete this reason and its review history?')) run(() => api.deleteThesis(thesis.id)) }}>Delete</button>
        </div>
      )}

      {!thesis.review_due && (
        <div className="thesis-demo">
          <span className="faint small"><b>Try it</b> — a thesis is a three-month instrument and you don't have three months. Pretend you wrote this…</span>
          {[10, 30, 90].map(n => (
            <button key={n} className="btn ghost sm" disabled={busy} onClick={() => run(() => api.rewindThesis(thesis.id, n))}>
              {n} sessions ago
            </button>
          ))}
          <span className="faint small">Moves your anchor to a real past close. The prompt then fires on its own merits, or doesn't.</span>
        </div>
      )}

      {thesis.reviews.length > 0 && <ReviewHistory reviews={thesis.reviews} />}
      {err && !thesis.review_due && <div className="err small">{err}</div>}
    </div>
  )
}

function ReviewPrompt({ thesis, busy, err, onAnswer, onSnooze }: {
  thesis: Thesis; busy: boolean; err: string | null
  onAnswer: (v: Verdict, note: string | null) => void
  onSnooze: () => void
}) {
  const [note, setNote] = useState('')
  return (
    <div className="thesis-prompt">
      <div className="tp-head"><span className={`tp-tag ${thesis.trigger}`}>{thesis.trigger}</span>Does this still hold?</div>
      <p className="tp-why">{thesis.trigger_text}</p>
      <textarea className="input ta" rows={2} value={note} onChange={e => setNote(e.target.value)}
                placeholder="What changed, or didn't? (optional — but this is the part you'll want in six months)" />
      <div className="tp-actions">
        <button className="btn sm ok" disabled={busy} onClick={() => onAnswer('holds', note.trim() || null)}>Still holds</button>
        <button className="btn sm warn" disabled={busy} onClick={() => onAnswer('weakened', note.trim() || null)}>Weaker now</button>
        <button className="btn sm bad" disabled={busy} onClick={() => onAnswer('broken', note.trim() || null)}>It broke</button>
        <span style={{ flex: 1 }} />
        <button className="btn ghost sm" disabled={busy} onClick={onSnooze} title="Silences this for a week. A 52-week breach still gets through.">Not now</button>
      </div>
      <div className="faint small">“It broke” closes this reason and keeps it in your record — it doesn't remove the stock.</div>
      {err && <div className="err small">{err}</div>}
    </div>
  )
}

export function ReviewHistory({ reviews }: { reviews: Thesis['reviews'] }) {
  return (
    <ol className="thesis-history">
      {reviews.map(r => (
        <li key={r.id} className={r.verdict}>
          <span className={`verdict ${r.verdict}`}>{r.verdict}</span>
          <span className="faint small">{dateIST(r.created_at)}</span>
          {r.change_pct != null && <span className={`num small ${sign(r.change_pct)}`}>{pct(r.change_pct)}</span>}
          {r.note && <span className="note">“{r.note}”</span>}
        </li>
      ))}
    </ol>
  )
}
