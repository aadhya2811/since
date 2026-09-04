import type { Briefing } from '../types'
import { pct, sign } from '../format'

interface Props {
  briefing: Briefing
  onClose: () => void
  onMarkAllSeen: () => void
  onRewind: (n: number) => void
}

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')

/** The popup you see the moment a visit starts: the briefing in five lines. */
export function WhatsNew({ briefing, onClose, onMarkAllSeen, onRewind }: Props) {
  const flagged = briefing.items.filter(i => i.tier !== 'quiet').slice(0, 5)
  const withSince = briefing.items.find(i => i.since)
  const sinceLabel = withSince?.since?.seen_label ?? 'you last looked'
  const first = briefing.first_visit

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
        {first ? (
          <>
            <div className="eyebrow">Baseline set</div>
            <h2>I've noted what you're seeing right now.</h2>
            <p>Next time you open Since, everything is measured from <em>this</em> moment — not from yesterday's close. Only stocks whose move is unusual <em>for them</em> will be flagged.</p>
            <div className="tip">
              <b>Don't want to wait?</b> Pretend you last checked a few sessions ago and see the briefing work on real history.
            </div>
            <div className="actions">
              <button className="btn ghost" onClick={onClose}>Just show the list</button>
              <button className="btn primary" onClick={() => onRewind(3)}>Pretend I last looked 3 sessions ago →</button>
            </div>
          </>
        ) : (
          <>
            <div className="eyebrow">Since {sinceLabel}</div>
            <h2>{briefing.summary.headline}</h2>
            {flagged.length === 0 ? (
              <p>Everything on your list moved within its normal range. Nothing needs you.</p>
            ) : (
              <div className="rows">
                {flagged.map(i => {
                  const move = i.reasons.find(r => r.kind === 'move' && r.severity !== 'low') ?? i.reasons.find(r => r.kind !== 'info')
                  const d = sign(i.since?.change_pct)
                  return (
                    <div key={i.symbol} className={`row ${i.tier}`}>
                      <span className="t">{ticker(i.symbol)}</span>
                      <span className="r" title={move?.text}>{move?.text ?? i.name}</span>
                      <span className={`num ${d}`} style={{ fontWeight: 700 }}>{pct(i.since?.change_pct)}</span>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="actions">
              {flagged.length > 0 && <button className="btn ghost" onClick={onMarkAllSeen}>Mark all seen</button>}
              <button className="btn primary" onClick={onClose}>Show me</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
