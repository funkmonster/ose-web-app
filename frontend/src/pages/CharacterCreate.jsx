import React, { useState } from 'react'
import { api } from '../api'

const CLASSES = ['Fighter', 'Magic-User', 'Cleric', 'Thief', 'Dwarf', 'Elf', 'Halfling']
const STATS = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']

export default function CharacterCreate({ onCreated, userName }) {
  const [stats, setStats] = useState(null)
  const [name, setName] = useState('')
  const [charClass, setCharClass] = useState('Fighter')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const rollStats = async () => {
    setBusy(true)
    try {
      const s = await api.rollStats()
      setStats(s)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const create = async () => {
    if (!name.trim() || !stats) return
    setBusy(true)
    setError('')
    try {
      const char = await api.createCharacter({
        name: name.trim(),
        char_class: charClass,
        str_score: stats.STR.value,
        dex_score: stats.DEX.value,
        con_score: stats.CON.value,
        int_score: stats.INT.value,
        wis_score: stats.WIS.value,
        cha_score: stats.CHA.value,
      })
      onCreated(char)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <div className="box">
        <h1>Roll Your Fate</h1>
        <p>
          Welcome, {userName}. Three dice, six scores, no take-backs.
          This is B/X — play the character the dice give you.
        </p>
        {error && <div className="error">{error}</div>}

        {!stats ? (
          <button onClick={rollStats} disabled={busy}>
            {busy ? 'The dice tumble…' : 'Roll 3d6 × 6'}
          </button>
        ) : (
          <>
            <div className="stat-roll-grid">
              {STATS.map((s) => (
                <div className="cell" key={s}>
                  <div className="v">{stats[s].value}</div>
                  <div className="l">
                    {s} ({stats[s].modifier >= 0 ? '+' : ''}{stats[s].modifier})
                  </div>
                </div>
              ))}
            </div>
            <input
              placeholder="Character name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <select value={charClass} onChange={(e) => setCharClass(e.target.value)}>
              {CLASSES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <button onClick={create} disabled={busy || !name.trim()}>
              {busy ? 'Inking the sheet…' : 'Join the Party'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
