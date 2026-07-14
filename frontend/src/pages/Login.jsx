import React, { useState } from 'react'

export default function Login({ onLogin }) {
  const [passphrase, setPass] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!passphrase.trim()) return
    setBusy(true)
    setError('')
    try {
      await onLogin(passphrase.trim())
    } catch (e) {
      setError(e.message === 'Invalid passphrase' ? 'That passphrase opens no doors here.' : e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <div className="box">
        <h1>The Borderlands Table</h1>
        <p>
          The road ends at a torchlit gate. A voice from the arrow slit above:
          "Speak the passphrase, traveler."
        </p>
        {error && <div className="error">{error}</div>}
        <input
          type="password"
          placeholder="passphrase"
          value={passphrase}
          onChange={(e) => setPass(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          autoFocus
        />
        <button onClick={submit} disabled={busy}>
          {busy ? 'The gate creaks…' : 'Enter the Keep'}
        </button>
      </div>
    </div>
  )
}
