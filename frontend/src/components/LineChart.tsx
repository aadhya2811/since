import { useMemo, useState } from 'react'

/** Multi-series line chart, indexed to a common base (100). One axis, direct
 *  labels at the line ends, legend, crosshair tooltip. Categorical colours are
 *  assigned in fixed order (validated for colour-vision deficiency on the dark
 *  surface) and follow the series, never its rank. */
export const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#9085e9']

interface Series { key: string; label: string; values: number[] }

export function LineChart({ series, dates, height = 300, baseline = 100, fmt = (v: number) => v.toFixed(1) }: {
  series: Series[]; dates: string[]; height?: number; baseline?: number; fmt?: (v: number) => string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 860, H = height, padL = 44, padR = 96, padT = 14, padB = 28
  const n = dates.length
  const { min, max } = useMemo(() => {
    const all = series.flatMap(s => s.values).concat([baseline])
    const lo = Math.min(...all), hi = Math.max(...all)
    const pad = (hi - lo || 1) * 0.08
    return { min: lo - pad, max: hi + pad }
  }, [series, baseline])
  if (n < 2 || series.length === 0) return <div className="faint small">Not enough data to draw.</div>
  const x = (i: number) => padL + (i / (n - 1)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB)
  const ticks = 5
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => min + (i / ticks) * (max - min))
  const xIdx = [0, Math.round((n - 1) / 3), Math.round(2 * (n - 1) / 3), n - 1]

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    const i = Math.round(((px - padL) / (W - padL - padR)) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, i)))
  }
  const hi = hover
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label="Performance, indexed to 100">
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke="rgba(255,255,255,.07)" />
            <text x={padL - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#6b7194" fontFamily="var(--mono)">{fmt(t)}</text>
          </g>
        ))}
        <line x1={padL} x2={W - padR} y1={y(baseline)} y2={y(baseline)} stroke="rgba(255,255,255,.22)" strokeDasharray="3 4" />
        {xIdx.map(i => <text key={i} x={x(i)} y={H - 8} textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'} fontSize="11" fill="#6b7194">{dates[i]?.slice(5)}</text>)}
        {series.map((s, si) => {
          const d = s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
          const c = SERIES_COLORS[si % SERIES_COLORS.length]
          const last = s.values[s.values.length - 1]
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={c} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              <circle cx={x(n - 1)} cy={y(last)} r={3.5} fill={c} stroke="#0d0f1a" strokeWidth={2} />
              <text x={x(n - 1) + 8} y={y(last) + 4} fontSize="12" fill="#eef0ff" fontWeight={600}>{s.label} <tspan fill="#a4a9c8" fontWeight={400} fontFamily="var(--mono)">{fmt(last)}</tspan></text>
            </g>
          )
        })}
        {hi != null && (
          <g>
            <line x1={x(hi)} x2={x(hi)} y1={padT} y2={H - padB} stroke="rgba(255,255,255,.3)" />
            {series.map((s, si) => <circle key={s.key} cx={x(hi)} cy={y(s.values[hi])} r={4} fill={SERIES_COLORS[si % SERIES_COLORS.length]} stroke="#0d0f1a" strokeWidth={2} />)}
          </g>
        )}
      </svg>
      {hi != null && (
        <div className="tooltip">
          <div className="faint small">{dates[hi]}</div>
          {series.map((s, si) => (
            <div key={s.key} className="tt-row"><i style={{ background: SERIES_COLORS[si % SERIES_COLORS.length] }} /><span>{s.label}</span><span className="num">{fmt(s.values[hi])}</span></div>
          ))}
        </div>
      )}
      <div className="legend">{series.map((s, si) => <span key={s.key}><i style={{ background: SERIES_COLORS[si % SERIES_COLORS.length] }} />{s.label}</span>)}</div>
    </div>
  )
}
