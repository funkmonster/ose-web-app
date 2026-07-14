import React, { useState } from 'react'
import { api } from '../api'

export default function PartyPanel({ party, user, physicalDiceMode, className = '' }) {
  return (
    <aside className={`panel party-panel ${className}`}>
      <h2>The Party</h2>
      {party.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
          No adventurers yet.
        </div>
      )}
      {party.map((c) => <PartyCard key={c.id} c={c} />)}
      {user.role === 'gm' && <GMTools party={party} physicalDiceMode={physicalDiceMode} />}
    </aside>
  )
}

function PartyCard({ c }) {
  const pct = c.hp_max > 0 ? (c.hp_current / c.hp_max) * 100 : 0
  return (
    <div className={`party-card ${c.alive ? '' : 'dead'}`}>
      <div className="name">{c.name}</div>
      <div className="meta">Lvl {c.level} {c.class} · AC {c.ac} · {c.gold} gp</div>
      <div className="hp-track">
        <div
          className={`hp-fill ${pct <= 35 ? 'hurt' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="hp-label">{c.hp_current}/{c.hp_max} HP · {c.xp} XP</div>
    </div>
  )
}

function GMTools({ party, physicalDiceMode }) {
  const [narration, setNarration] = useState('')
  const [target, setTarget] = useState('')
  const [delta, setDelta] = useState(-1)
  const [msg, setMsg] = useState('')

  const toggleDiceMode = async (enabled) => {
    try {
      await api.setPhysicalDiceMode(enabled)
      setMsg('')
    } catch (e) {
      setMsg(e.message)
    }
  }

  const say = async () => {
    if (!narration.trim()) return
    try {
      await api.gmSay(narration.trim())
      setNarration('')
      setMsg('')
    } catch (e) {
      setMsg(e.message)
    }
  }

  const applyHP = async () => {
    if (!target) return
    try {
      await api.gmUpdateHP(target, Number(delta))
      setMsg('')
    } catch (e) {
      setMsg(e.message)
    }
  }

  return (
    <div className="gm-tools">
      <h2>GM Tools</h2>
      {msg && <div style={{ color: 'var(--magenta)', fontSize: 12, marginBottom: 6 }}>{msg}</div>}
      <label className="row" style={{ alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <input
          type="checkbox"
          checked={physicalDiceMode}
          onChange={(e) => toggleDiceMode(e.target.checked)}
        />
        Physical dice mode
      </label>
      <textarea
        placeholder="Narrate directly (bypasses the LLM)"
        value={narration}
        onChange={(e) => setNarration(e.target.value)}
      />
      <button onClick={say} style={{ width: '100%', marginBottom: 10 }}>Narrate</button>
      <div className="row">
        <select value={target} onChange={(e) => setTarget(e.target.value)} style={{ flex: 1 }}>
          <option value="">— character —</option>
          {party.map((c) => (
            <option key={c.id} value={c.discord_user_id}>{c.name}</option>
          ))}
        </select>
        <input
          type="number"
          value={delta}
          onChange={(e) => setDelta(e.target.value)}
        />
      </div>
      <button onClick={applyHP} style={{ width: '100%' }}>Apply HP change</button>
    </div>
  )
}
