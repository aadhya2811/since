import type { Briefing } from '../types'
import { Sparkline } from './Sparkline'
import { pct, sign } from '../format'

/** The command strip: five numbers that answer "should I be reading further?"
 *
 * Everything here is already computed for other parts of the page — this is a
 * layout decision, not a new data source. It sits above the fold so the
 * default answer to "anything happen?" costs one glance, not a scroll. */
export function CommandStrip({ briefing, onJumpAttention, onOpenMemory }: {
  briefing: Briefing
  onJumpAttention: () => void
  onOpenMemory: () => void
}) {
  const s = briefing.summary
  return (
    <div className="cstrip">
      {briefing.indices.map(ix => (
        <div className="cs-cell idx" key={ix.symbol}>
          <div className="cs-k">{ix.name}</div>
          <div className="cs-v num">
            {ix.price != null ? ix.price.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}
            <span className={`cs-d ${sign(ix.ret_1d)}`}>{pct(ix.ret_1d)}</span>
          </div>
          <div className="cs-spark"><Sparkline data={ix.sparkline} width={78} height={20} /></div>
        </div>
      ))}

      <div className="cs-cell">
        <div className="cs-k">Since you looked</div>
        <div className={`cs-v num ${sign(s.net_change_pct)}`}>{s.net_change_pct == null ? '—' : pct(s.net_change_pct)}</div>
        <div className="cs-sub faint">{s.net_change_pct == null
          ? 'no new prints since your last visit'
          : `your list, equal-weighted (${s.attention + s.notable + s.quiet})`}</div>
      </div>

      <button className={`cs-cell act ${s.attention ? 'hot' : ''}`} onClick={onJumpAttention}>
        <div className="cs-k">Needs attention</div>
        <div className="cs-v num">{s.attention}</div>
        <div className="cs-sub faint">{s.notable} more worth a glance</div>
      </button>

      <button className={`cs-cell act ${s.theses_due ? 'hot' : ''}`} onClick={onOpenMemory}>
        <div className="cs-k">Reasons to re-read</div>
        <div className="cs-v num">{s.theses_due}</div>
        <div className="cs-sub faint">{s.theses_open} thes{s.theses_open === 1 ? 'is' : 'es'} on file</div>
      </button>
    </div>
  )
}
