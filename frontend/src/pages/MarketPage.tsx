import { useEffect, useState } from 'react'
import { api } from '../api'
import type { MarketPage as MarketData, MoverOut } from '../types'
import { inr, pct, sign } from '../format'
import { Sparkline } from '../components/Sparkline'

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')

/** What's moving, across a wider universe than your list. Information, not advice. */
export function MarketPage({ onAdd }: { onAdd: (symbol: string) => Promise<void> }) {
  const [d, setD] = useState<MarketData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.market().then(setD).catch(e => setErr((e as Error).message))
    const iv = window.setInterval(() => api.market().then(setD).catch(() => {}), 60_000)
    return () => window.clearInterval(iv)
  }, [])
  if (err) return <div className="banner">{err}</div>
  if (!d) return <div className="list" style={{ marginTop: 20 }}><div className="skeleton" /><div className="skeleton" /></div>

  const nifty = d.indices.find(i => i.symbol === '^NSEI')
  const tone = nifty?.ret_5d == null ? '' : nifty.ret_5d > 0.01 ? 'Risk-on week.' : nifty.ret_5d < -0.01 ? 'Risk-off week.' : 'A flat week for the index.'

  return (
    <>
      <div className="headline">
        <h2>{nifty ? `Nifty ${pct(nifty.ret_5d)} this week. ${tone}` : 'Market'}</h2>
        <div className="sub">Across {d.scanned} of {d.universe_size} large NSE names · {d.is_open ? 'live session' : `as of ${d.session_date}`} · what happened, not what to buy.</div>
      </div>

      <div className="tiles" style={{ marginTop: 14 }}>
        {d.indices.map(ix => (
          <div key={ix.symbol} className="tile" style={{ cursor: 'default' }}>
            <div className="tile-top"><span className="t">{ix.name}</span></div>
            <div className="tile-price num">{ix.price != null ? ix.price.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}</div>
            <div className="tile-row"><span className={`num ${sign(ix.ret_1d)}`}>{pct(ix.ret_1d)} <span className="faint">today</span></span><Sparkline data={ix.sparkline} width={64} height={20} /></div>
            <div className="tile-since num"><span className={sign(ix.ret_5d)}>{pct(ix.ret_5d)}</span> <span className="faint">5 sessions</span> · <span className={sign(ix.ret_20d)}>{pct(ix.ret_20d)}</span> <span className="faint">20</span></div>
          </div>
        ))}
      </div>

      {d.scanned < 10 && <div className="banner" style={{ marginTop: 14 }}>Still scanning the universe — history for {d.universe_size - d.scanned} more names arrives over the next few minutes.</div>}

      <section className="section panel">
        <div className="section-h"><h3>Sectors this week</h3><span className="faint small">equal-weighted average of the names we track in each</span></div>
        <div className="sectors">
          {d.sectors.map(s => {
            const v = s.ret_5d ?? 0
            const w = Math.min(100, Math.abs(v) * 1000)
            return (
              <div key={s.sector} className="sector-row" title={s.members.map(ticker).join(', ')}>
                <span className="sec-name">{s.sector} <span className="faint">{s.n}</span></span>
                <span className="sec-bar"><span className="neg">{v < 0 && <i style={{ width: `${w}%` }} />}</span><span className="pos">{v > 0 && <i style={{ width: `${w}%` }} />}</span></span>
                <span className={`num ${sign(s.ret_5d)}`}>{pct(s.ret_5d)}</span>
                <span className={`num faint`}>{pct(s.ret_20d)} <span>20d</span></span>
              </div>
            )
          })}
        </div>
      </section>

      <div className="cols">
        <Movers title="Biggest gainers, 5 sessions" items={d.gainers_5d} onAdd={onAdd} />
        <Movers title="Biggest losers, 5 sessions" items={d.losers_5d} onAdd={onAdd} />
      </div>
      <div className="cols">
        <Movers title="Most unusual moves" sub="biggest move relative to each stock's own normal" items={d.unusual_5d} onAdd={onAdd} showZ />
        <div>
          <Movers title="At 52-week highs" items={d.highs_52w} onAdd={onAdd} empty="None right now." />
          <Movers title="At 52-week lows" items={d.lows_52w} onAdd={onAdd} empty="None right now." />
        </div>
      </div>

      <p className="faint small" style={{ marginTop: 18 }}>This page describes what prices did. It is not a recommendation to buy or sell anything — Since doesn't give investment advice.</p>
    </>
  )
}

function Movers({ title, sub, items, onAdd, showZ, empty }: { title: string; sub?: string; items: MoverOut[]; onAdd: (s: string) => Promise<void>; showZ?: boolean; empty?: string }) {
  return (
    <section className="section panel">
      <div className="section-h"><h3>{title}</h3>{sub && <span className="faint small">{sub}</span>}</div>
      {items.length === 0 ? <div className="faint small">{empty ?? 'Nothing yet.'}</div> : (
        <div className="movers">
          {items.map(m => (
            <div key={m.symbol} className="mover">
              <div className="mv-main">
                <span className="mv-sym">{ticker(m.symbol)} <span className="faint">{m.sector}</span></span>
                <span className="mv-name">{m.name}</span>
              </div>
              <Sparkline data={m.sparkline} width={70} height={22} />
              <span className="num mv-price">{inr(m.price)}</span>
              <span className={`num mv-ret ${sign(m.ret_5d)}`}>{pct(m.ret_5d)}{showZ && m.z_5d != null ? <span className="faint"> · {Math.abs(m.z_5d).toFixed(1)}σ</span> : null}</span>
              <button className="btn ghost sm" title="Add to the current watchlist" onClick={() => onAdd(m.symbol)}>+ watch</button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
