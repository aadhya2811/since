import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { SymbolHit } from '../types'

export function AddSymbol({ onAdd, existing }: { onAdd: (symbol: string) => Promise<void>; existing: Set<string> }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SymbolHit[]>([])
  const [open, setOpen] = useState(false)
  const [hl, setHl] = useState(0)
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => api.search(q).then(setHits).catch(() => setHits([])), 120)
    return () => clearTimeout(t)
  }, [q, open])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  async function pick(symbol: string) {
    setBusy(true)
    try { await onAdd(symbol); setQ(''); setOpen(false) } finally { setBusy(false) }
  }

  const visible = hits.filter(h => !existing.has(h.symbol))

  return (
    <div className="add" ref={box}>
      <input
        className="input" placeholder="Add a stock — try 'tcs', 'hal', or any NSE ticker" value={q}
        onFocus={() => setOpen(true)} onChange={e => { setQ(e.target.value); setOpen(true); setHl(0) }}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { setHl(h => Math.min(h + 1, visible.length - 1)); e.preventDefault() }
          if (e.key === 'ArrowUp') { setHl(h => Math.max(h - 1, 0)); e.preventDefault() }
          if (e.key === 'Enter') { e.preventDefault(); const h = visible[hl]; pick(h ? h.symbol : q.trim()) }
          if (e.key === 'Escape') setOpen(false)
        }}
        disabled={busy}
      />
      {open && (visible.length > 0 || q.trim()) && (
        <div className="results">
          {visible.map((h, i) => (
            <button key={h.symbol} className={i === hl ? 'hl' : ''} onMouseEnter={() => setHl(i)} onClick={() => pick(h.symbol)}>
              <span className="s">{h.symbol.replace('.NS', '')}</span><span className="n">{h.name}</span><span className="sec">{h.sector}</span>
            </button>
          ))}
          {q.trim() && !visible.some(h => h.symbol.replace('.NS', '').toLowerCase() === q.trim().toLowerCase()) && (
            <button onClick={() => pick(q.trim())}><span className="s">{q.trim().toUpperCase()}</span><span className="n muted">Add as ticker (validated against the data feed)</span></button>
          )}
        </div>
      )}
    </div>
  )
}
