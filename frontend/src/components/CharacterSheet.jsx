import React, { useState } from 'react'
import { api } from '../api'

const MOD_TABLE = (v) =>
  v <= 3 ? -3 : v <= 5 ? -2 : v <= 8 ? -1 : v <= 12 ? 0 : v <= 15 ? 1 : v <= 17 ? 2 : 3

const fmtMod = (m) => (m >= 0 ? `+${m}` : `${m}`)

export default function CharacterSheet({ character: c, setCharacter, className = '' }) {
  if (!c || !c.name) return <aside className={`panel right sheet-panel ${className}`} />

  return (
    <aside className={`panel right sheet-panel ${className}`}>
      <div className="sheet-header">
        <div className="char-name">{c.name}</div>
        <div className="char-class">Level {c.level} {c.race} {c.class}</div>
      </div>

      <div className="vitals">
        <div className="stat">
          <div className="label">HP</div>
          <div className="value" style={{ color: c.hp_current <= c.hp_max * 0.35 ? 'var(--magenta)' : undefined }}>
            {c.hp_current}/{c.hp_max}
          </div>
        </div>
        <div className="stat">
          <div className="label">AC</div>
          <div className="value">{c.ac}</div>
        </div>
        <div className="stat">
          <div className="label">GOLD</div>
          <div className="value">{c.gold}</div>
        </div>
      </div>

      <div className="stat-grid">
        {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((s) => (
          <div className="stat" key={s}>
            <div className="label">{s.toUpperCase()}</div>
            <div className="value">{c[s]}</div>
            <div className="mod">{fmtMod(MOD_TABLE(c[s]))}</div>
          </div>
        ))}
      </div>

      <EditableList
        title="Weapons & Armour"
        items={c.weapons_armor || []}
        onSave={async (items) => {
          await api.updateWeaponsArmor(items)
          setCharacter({ ...c, weapons_armor: items })
        }}
        placeholder="Sword, Chain mail…"
      />

      <EditableList
        title="Inventory"
        items={c.inventory || []}
        onSave={async (items) => {
          await api.updateInventory(items)
          setCharacter({ ...c, inventory: items })
        }}
        placeholder="Torch, 50' rope…"
      />

      {['Magic-User', 'Cleric', 'Elf'].includes(c.class) && (
        <EditableList
          title="Spells"
          items={c.spells || []}
          onSave={async (items) => {
            await api.updateSpells(items)
            setCharacter({ ...c, spells: items })
          }}
          placeholder="Sleep, Magic Missile…"
        />
      )}

      <div className="sheet-section">
        <h3>Experience</h3>
        <div style={{ fontSize: 13 }}>{c.xp} XP</div>
      </div>
    </aside>
  )
}

function EditableList({ title, items, onSave, placeholder }) {
  const [draft, setDraft] = useState('')
  const [err, setErr] = useState('')

  const add = async () => {
    const v = draft.trim()
    if (!v) return
    try {
      await onSave([...items, v])
      setDraft('')
      setErr('')
    } catch (e) {
      setErr(e.message)
    }
  }

  const remove = async (idx) => {
    try {
      await onSave(items.filter((_, i) => i !== idx))
      setErr('')
    } catch (e) {
      setErr(e.message)
    }
  }

  return (
    <div className="sheet-section">
      <h3>{title}</h3>
      {err && <div style={{ color: 'var(--magenta)', fontSize: 12 }}>{err}</div>}
      <ul className="sheet-list">
        {items.map((item, i) => (
          <li key={i}>
            <span>{item}</span>
            <button onClick={() => remove(i)} aria-label={`Remove ${item}`}>✕</button>
          </li>
        ))}
      </ul>
      <div className="add-item">
        <input
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
        />
        <button onClick={add}>Add</button>
      </div>
    </div>
  )
}
