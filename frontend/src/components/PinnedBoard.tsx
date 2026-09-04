import type { BriefingItem } from '../types'
import { inr, pct, sign } from '../format'
import { Sparkline } from './Sparkline'

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')

/** The always-on strip: just the numbers for the symbols you pinned, across
 *  every watchlist. Click a tile to jump to its full card. */
export function PinnedBoard({ items, onOpen, onUnpin }: {
  items: BriefingItem[]
  onOpen: (item: BriefingItem) => void
  onUnpin: (symbol: string) => void
}) {
  if (items.length === 0) return null
  return (
    <section className="board">
      <div className="section-h"><h3>Pinned</h3><span className="count">{items.length}</span><span className="spacer" /><span className="faint small">click a tile to open it</span></div>
      <div className="tiles">
        {items.map(it => {
          const q = it.quote, s = it.since
          const d = sign(s?.change_pct)
          return (
            <div key={it.symbol} className={`tile ${it.tier}`} onClick={() => onOpen(it)} title={it.name}>
              <div className="tile-top">
                <span className="t">{ticker(it.symbol)}</span>
                <button className="unpin" title="Unpin" onClick={e => { e.stopPropagation(); onUnpin(it.symbol) }}>×</button>
              </div>
              <div className="tile-price num">{inr(q?.price)}</div>
              <div className="tile-row">
                <span className={`num ${sign(q?.day_change_pct)}`}>{pct(q?.day_change_pct)} <span className="faint">today</span></span>
                <Sparkline data={it.sparkline} width={64} height={20} baseline={s?.baseline_price ?? null} />
              </div>
              <div className={`tile-since num ${d}`}>{pct(s?.change_pct)} <span className="faint">since {s?.seen_label ?? '—'}</span></div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
