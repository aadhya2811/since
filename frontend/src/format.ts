export const inr = (x: number | null | undefined, digits?: number) =>
  x == null ? '—' : '₹' + x.toLocaleString('en-IN', { minimumFractionDigits: digits ?? (x >= 1000 ? 0 : 2), maximumFractionDigits: digits ?? (x >= 1000 ? 0 : 2) })

export const pct = (x: number | null | undefined, signed = true) => {
  if (x == null) return '—'
  if (Math.abs(x) < 0.0005) return '0.0%'
  return (signed && x > 0 ? '+' : '') + (x * 100).toFixed(1) + '%'
}

export const compact = (n: number | null | undefined) => {
  if (n == null) return '—'
  if (n >= 1e7) return (n / 1e7).toFixed(1) + ' Cr'
  if (n >= 1e5) return (n / 1e5).toFixed(1) + ' L'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

const IST = 'Asia/Kolkata'
export const timeIST = (iso: string | null | undefined) =>
  iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleTimeString('en-IN', { timeZone: IST, hour: '2-digit', minute: '2-digit' }) : '—'
export const dateIST = (iso: string | null | undefined) =>
  iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleDateString('en-IN', { timeZone: IST, day: 'numeric', month: 'short' }) : '—'
export const dateTimeIST = (iso: string | null | undefined) =>
  iso ? `${dateIST(iso)}, ${timeIST(iso)}` : '—'

export const ago = (iso: string) => {
  const ms = Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()
  const m = Math.round(ms / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  return d === 1 ? 'yesterday' : `${d}d ago`
}

export const sign = (x: number | null | undefined): 'up' | 'down' | 'flat' => (x == null || Math.abs(x) < 1e-9 ? 'flat' : x > 0 ? 'up' : 'down')
