import { useState } from 'react'
import { api, auth, deviceLabel } from '../api'
import type { User } from '../types'

export function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [devCode, setDevCode] = useState<string | null>(null)
  const [stage, setStage] = useState<'email' | 'code'>('email')
  const [device, setDevice] = useState(deviceLabel())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function request(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      const r = await api.requestCode(email.trim())
      setDevCode(r.dev_code); setStage('code')
      if (r.dev_code) setCode(r.dev_code)
    } catch (ex) { setErr((ex as Error).message) } finally { setBusy(false) }
  }
  async function verify(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      const r = await api.verify(email.trim(), code.trim(), device.trim() || deviceLabel())
      auth.set(r.token); onLogin(r.user)
    } catch (ex) { setErr((ex as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="login">
      <h1>Since<span>.</span></h1>
      <p>A watchlist that opens as a briefing: what changed since <em>you</em> last looked, and what deserves your attention now.</p>
      {stage === 'email' ? (
        <form onSubmit={request}>
          <input className="input" type="email" required placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)} autoFocus />
          <input className="input" placeholder="This device (e.g. Laptop)" value={device} onChange={e => setDevice(e.target.value)} />
          <button className="btn primary" disabled={busy}>Send me a code</button>
          <div className="hint">No password. Sign in on any device with the same email and your watchlist follows you.</div>
          {err && <div className="err">{err}</div>}
        </form>
      ) : (
        <form onSubmit={verify}>
          {devCode ? (
            <>
              <div className="hint">Dev mode — no email is sent. Your code:</div>
              <div className="code">{devCode}</div>
            </>
          ) : <div className="hint">We sent a 6-digit code to {email}.</div>}
          <input className="input" inputMode="numeric" placeholder="6-digit code" value={code} onChange={e => setCode(e.target.value)} autoFocus />
          <button className="btn primary" disabled={busy}>Sign in</button>
          <button type="button" className="btn ghost" onClick={() => setStage('email')}>Use a different email</button>
          {err && <div className="err">{err}</div>}
        </form>
      )}
    </div>
  )
}
