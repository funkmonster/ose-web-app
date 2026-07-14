import React, { useState } from 'react'
import { api } from '../api'

const CLASSES = ['Fighter', 'Magic-User', 'Cleric', 'Thief', 'Dwarf', 'Elf', 'Halfling']
const STATS = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']

const emptyPregen = {
  name: '',
  charClass: 'Fighter',
  race: '',
  str: 10, dex: 10, con: 10, int: 10, wis: 10, cha: 10,
  hp: 8,
  ac: 9,
  gold: 0,
  inventory: '',
  spells: '',
}

export default function CharacterCreate({ onCreated, userName }) {
  const [mode, setMode] = useState('roll')
  const [stats, setStats] = useState(null)
  const [name, setName] = useState('')
  const [charClass, setCharClass] = useState('Fighter')
  const [pregen, setPregen] = useState(emptyPregen)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const switchMode = (m) => {
    setMode(m)
    setError('')
  }

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

  const setField = (field) => (e) => {
    const raw = e.target.value
    const numeric = ['str', 'dex', 'con', 'int', 'wis', 'cha', 'hp', 'ac', 'gold']
    setPregen({ ...pregen, [field]: numeric.includes(field) ? Number(raw) : raw })
  }

  const createPregen = async () => {
    if (!pregen.name.trim()) return
    setBusy(true)
    setError('')
    try {
      const toList = (text) =>
        text.split('\n').map((s) => s.trim()).filter(Boolean)
      const char = await api.createCharacter({
        name: pregen.name.trim(),
        char_class: pregen.charClass,
        race: pregen.race.trim() || undefined,
        str_score: pregen.str,
        dex_score: pregen.dex,
        con_score: pregen.con,
        int_score: pregen.int,
        wis_score: pregen.wis,
        cha_score: pregen.cha,
        hp_max: pregen.hp,
        ac: pregen.ac,
        gold: pregen.gold,
        inventory: toList(pregen.inventory),
        spells: toList(pregen.spells),
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
        <h1>{mode === 'roll' ? 'Roll Your Fate' : 'Bring Your Own Hero'}</h1>
        <div className="mode-toggle">
          <button
            className={mode === 'roll' ? 'active' : ''}
            onClick={() => switchMode('roll')}
            disabled={busy}
          >
            Roll a New Character
          </button>
          <button
            className={mode === 'pregen' ? 'active' : ''}
            onClick={() => switchMode('pregen')}
            disabled={busy}
          >
            Use a Pre-Generated Character
          </button>
        </div>
        {error && <div className="error">{error}</div>}

        {mode === 'roll' ? (
          <>
            <p>
              Welcome, {userName}. Three dice, six scores, no take-backs.
              This is B/X — play the character the dice give you.
            </p>
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
          </>
        ) : (
          <>
            <p>
              Welcome, {userName}. Already have a character sheet? Bring it in
              as-is — no rolling, no surprises.
            </p>
            <input
              placeholder="Character name"
              value={pregen.name}
              onChange={setField('name')}
            />
            <select value={pregen.charClass} onChange={setField('charClass')}>
              {CLASSES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <input
              placeholder="Race (optional, defaults from class)"
              value={pregen.race}
              onChange={setField('race')}
            />
            <div className="stat-roll-grid">
              {STATS.map((s) => (
                <div className="cell" key={s}>
                  <input
                    type="number"
                    min={3}
                    max={18}
                    value={pregen[s.toLowerCase()]}
                    onChange={setField(s.toLowerCase())}
                  />
                  <div className="l">{s}</div>
                </div>
              ))}
            </div>
            <label>
              HP (max)
              <input type="number" min={1} value={pregen.hp} onChange={setField('hp')} />
            </label>
            <label>
              AC
              <input type="number" value={pregen.ac} onChange={setField('ac')} />
            </label>
            <label>
              Gold
              <input type="number" min={0} value={pregen.gold} onChange={setField('gold')} />
            </label>
            <label>
              Inventory (one item per line)
              <textarea value={pregen.inventory} onChange={setField('inventory')} />
            </label>
            <label>
              Spells (one per line)
              <textarea value={pregen.spells} onChange={setField('spells')} />
            </label>
            <button onClick={createPregen} disabled={busy || !pregen.name.trim()}>
              {busy ? 'Inking the sheet…' : 'Join the Party'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
