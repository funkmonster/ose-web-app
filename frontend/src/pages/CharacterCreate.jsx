import React, { useState } from 'react'
import { api } from '../api'

const CLASSES = ['Fighter', 'Magic-User', 'Cleric', 'Thief', 'Dwarf', 'Elf', 'Halfling']
const STATS = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']

const empty = {
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
  const [sheet, setSheet] = useState(empty)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const setField = (field) => (e) => {
    const raw = e.target.value
    const numeric = ['str', 'dex', 'con', 'int', 'wis', 'cha', 'hp', 'ac', 'gold']
    setSheet({ ...sheet, [field]: numeric.includes(field) ? Number(raw) : raw })
  }

  const create = async () => {
    if (!sheet.name.trim()) return
    setBusy(true)
    setError('')
    try {
      const toList = (text) =>
        text.split('\n').map((s) => s.trim()).filter(Boolean)
      const char = await api.createCharacter({
        name: sheet.name.trim(),
        char_class: sheet.charClass,
        race: sheet.race.trim() || undefined,
        str_score: sheet.str,
        dex_score: sheet.dex,
        con_score: sheet.con,
        int_score: sheet.int,
        wis_score: sheet.wis,
        cha_score: sheet.cha,
        hp_max: sheet.hp,
        ac: sheet.ac,
        gold: sheet.gold,
        inventory: toList(sheet.inventory),
        spells: toList(sheet.spells),
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
        <h1>Bring Your Character to the Table</h1>
        <p>
          Welcome, {userName}. This table works characters out ahead of time —
          enter the sheet your party already settled on at session zero,
          exactly as written. No dice, no surprises.
        </p>
        {error && <div className="error">{error}</div>}

        <input
          placeholder="Character name"
          value={sheet.name}
          onChange={setField('name')}
        />
        <select value={sheet.charClass} onChange={setField('charClass')}>
          {CLASSES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <input
          placeholder="Race (optional, defaults from class)"
          value={sheet.race}
          onChange={setField('race')}
        />
        <div className="stat-roll-grid">
          {STATS.map((s) => (
            <div className="cell" key={s}>
              <input
                type="number"
                min={3}
                max={18}
                value={sheet[s.toLowerCase()]}
                onChange={setField(s.toLowerCase())}
              />
              <div className="l">{s}</div>
            </div>
          ))}
        </div>
        <label>
          HP (max)
          <input type="number" min={1} value={sheet.hp} onChange={setField('hp')} />
        </label>
        <label>
          AC
          <input type="number" value={sheet.ac} onChange={setField('ac')} />
        </label>
        <label>
          Gold
          <input type="number" min={0} value={sheet.gold} onChange={setField('gold')} />
        </label>
        <label>
          Inventory (one item per line)
          <textarea value={sheet.inventory} onChange={setField('inventory')} />
        </label>
        <label>
          Spells (one per line)
          <textarea value={sheet.spells} onChange={setField('spells')} />
        </label>
        <button onClick={create} disabled={busy || !sheet.name.trim()}>
          {busy ? 'Inking the sheet…' : 'Join the Party'}
        </button>
      </div>
    </div>
  )
}
