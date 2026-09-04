import { useEffect, useState } from 'react'
import { api } from '../api'
import type { CompareOut, SymbolHit, Watchlist } from '../types'
import { compact, inr, pct } from '../format'
import { LineChart, SERIES_COLORS } from '../components/LineChart'

const ticker = (s: string) => s.replace(/\.NS$/, '').replace(/^\^/, '')

const HELP = {
  ret: 'Total change over the window, first close to latest price.',
  vol: 'Annualised volatility: how much the price typically swings. 20% is a calm large-cap; 50%+ is a wild one.',
  mdd: 'Max drawdown: the worst peak-to-trough fall inside the window. How bad it got if you bought the top.',
  r52: 'Where today\'s price sits between the 52-week low (0%) and high (100%).',
  volm: 'Average shares traded per day over the last 20 sessions. Higher = easier to buy and sell.',
  corr: 'Correlation of daily moves, −1 to +1. Near +1: they move together (little diversification). Near 0: independent.',
}

/** Put a few stocks side by side: same chart, same base, plus the numbers that
 *  make them different. No predictions. */
export function ComparePage({ lists }: { lists: Watchlist[] }) {
  const all = Array.from(new Set(lists.flatMap(l => l.items.map(i => i.symbol))))
  const [picked, setPicked] = useState<string[]>(() => all.slice(0, 3))
  const [sessions, setSessions] = useState(60)
  const [data, setData] = useState<CompareOut | null>(null)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SymbolHit[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (picked.length === 0) { setData(null); return }
    setBusy(true)
    api.compare(picked, sessions).then(d => { setData(d); setErr(null) }).catch(e => setErr((e as Error).message)).finally(() => setBusy(false))
  }, [picked, sessions])

  useEffect(() => {
    if (!q.trim()) { setHits([]); return }
    const t = setTimeout(() => api.search(q).then(h => setHits(h.filter(x => !picked.includes(x.symbol)).slice(0, 6))).catch(() => {}), 120)
    return () => clearTimeout(t)
  }, [q, picked])

  const add = (s: string) => { if (picked.length < 6 && !picked.includes(s)) setPicked([...picked, s]); setQ(''); setHits([]) }
  const remove = (s: string) => setPicked(picked.filter(x => x !== s))

  return (
    <>
      <div className="headline">
        <h2>Compare.</h2>
        <div className="sub">Same chart, same starting point (100), so you can see which one actually moved — and the numbers that make them different.</div>
      </div>

      <div className="picker">
        {picked.map((s, i) => (
          <span key={s} className="pick" style={{ borderColor: SERIES_COLORS[i] }}><i style={{ background: SERIES_COLORS[i] }} />{ticker(s)}<button onClick={() => remove(s)} title="Remove">×</button></span>
        ))}
        {picked.length < 6 && (
          <span className="add" style={{ margin: 0, flex: 1, minWidth: 180 }}>
            <input className="input" style={{ padding: '7px 10px' }} placeholder="Add a stock to compare…" value={q} onChange={e => setQ(e.target.value)}
                   onKeyDown={e => { if (e.key === 'Enter' && q.trim()) add(hits[0]?.symbol ?? q.trim()) }} />
            {hits.length > 0 && <div className="results">{hits.map(h => <button key={h.symbol} onClick={() => add(h.symbol)}><span className="s">{ticker(h.symbol)}</span><span className="n">{h.name}</span></button>)}</div>}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <div className="seg">{[20, 60, 120, 250].map(n => <button key={n} className={sessions === n ? 'on' : ''} onClick={() => setSessions(n)}>{n === 250 ? '1y' : n === 120 ? '6m' : n === 60 ? '3m' : '1m'}</button>)}</div>
        {all.length > 0 && picked.length === 0 && <button className="btn sm" onClick={() => setPicked(all.slice(0, 3))}>Use my watchlist</button>}
      </div>

      {err && <div className="banner">{err}</div>}
      {picked.length === 0 && <div className="empty"><h3>Pick two or more stocks</h3><p>Type a name above, or add from your watchlist.</p></div>}

      {data && data.series.length > 0 && (
        <>
          <section className="section panel">
            <div className="section-h"><h3>Performance, indexed to 100</h3><span className="count">{data.sessions} sessions</span><span className="spacer" />{busy && <span className="faint small">updating…</span>}</div>
            <LineChart dates={data.dates} series={data.series.map(s => ({ key: s.symbol, label: ticker(s.symbol), values: s.rebased }))} fmt={v => v.toFixed(0)} />
          </section>

          <section className="section panel">
            <div className="section-h"><h3>The numbers</h3><span className="faint small">hover a column header for what it means</span></div>
            <div className="tablewrap">
              <table className="cmp">
                <thead><tr><th>Stock</th><th>Price</th><th title={HELP.ret}>Return</th><th title={HELP.vol}>Volatility</th><th title={HELP.mdd}>Max drawdown</th><th title={HELP.r52}>52-wk position</th><th title={HELP.volm}>Avg volume</th><th>Best / worst day</th></tr></thead>
                <tbody>
                  {data.series.map((s, i) => (
                    <tr key={s.symbol}>
                      <td><i className="swatch" style={{ background: SERIES_COLORS[i] }} /><b>{ticker(s.symbol)}</b> <span className="faint">{s.name}</span></td>
                      <td className="num">{inr(s.last_price)}</td>
                      <td className={`num ${s.return_pct >= 0 ? 'up' : 'down'}`}>{pct(s.return_pct)}</td>
                      <td className="num">{(s.volatility_annual * 100).toFixed(0)}%</td>
                      <td className="num down">{pct(s.max_drawdown)}</td>
                      <td>{s.range_position_52w != null ? <span className="minibar"><span className="track"><i style={{ width: `${Math.round(s.range_position_52w * 100)}%` }} /></span><span className="num">{Math.round(s.range_position_52w * 100)}%</span></span> : '—'}</td>
                      <td className="num">{compact(s.avg_volume_20d)}</td>
                      <td className="num"><span className="up">{pct(s.best_day)}</span> / <span className="down">{pct(s.worst_day)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {data.series.length >= 2 && (
            <section className="section panel">
              <div className="section-h"><h3 title={HELP.corr}>How much they move together</h3><span className="faint small">correlation of daily moves · +1 together · 0 unrelated · −1 opposite</span></div>
              <div className="tablewrap">
                <table className="corr">
                  <thead><tr><th></th>{data.series.map(s => <th key={s.symbol}>{ticker(s.symbol)}</th>)}</tr></thead>
                  <tbody>
                    {data.series.map((a, i) => (
                      <tr key={a.symbol}><th>{ticker(a.symbol)}</th>
                        {data.series.map((b, j) => {
                          const v = data.correlation[i]?.[j]
                          const t = v == null ? 0 : v
                          const bg = i === j ? 'transparent' : t >= 0 ? `rgba(99,102,241,${(0.08 + 0.55 * t).toFixed(2)})` : `rgba(251,113,133,${(0.08 + 0.55 * -t).toFixed(2)})`
                          return <td key={b.symbol} className="num" style={{ background: bg }}>{v == null ? '—' : i === j ? '·' : (Math.abs(v) < 0.005 ? 0 : v).toFixed(2)}</td>
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </>
  )
}
