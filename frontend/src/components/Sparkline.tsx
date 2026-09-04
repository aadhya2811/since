export function Sparkline({ data, width = 96, height = 30, baseline }: { data: number[]; width?: number; height?: number; baseline?: number | null }) {
  if (!data || data.length < 2) return <svg width={width} height={height} />
  const all = baseline != null ? [...data, baseline] : data
  const min = Math.min(...all), max = Math.max(...all)
  const span = max - min || 1
  const x = (i: number) => (i / (data.length - 1)) * (width - 2) + 1
  const y = (v: number) => height - 2 - ((v - min) / span) * (height - 4)
  const d = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const up = data[data.length - 1] >= data[0]
  const color = up ? 'var(--up)' : 'var(--down)'
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="spark">
      {baseline != null && baseline >= min && baseline <= max && (
        <line x1={0} x2={width} y1={y(baseline)} y2={y(baseline)} stroke="var(--text-3)" strokeDasharray="2 3" strokeWidth={1} />
      )}
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
