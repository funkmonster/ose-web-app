import React, { useState, useEffect, useCallback } from 'react'
import { api, getPassphrase, setPassphrase, clearPassphrase } from './api'
import { useGameSocket } from './hooks/useGameSocket'
import Login from './pages/Login'
import CharacterCreate from './pages/CharacterCreate'
import GameView from './components/GameView'
import PartyPanel from './components/PartyPanel'
import CharacterSheet from './components/CharacterSheet'

export default function App() {
  const [user, setUser] = useState(null)
  const [checked, setChecked] = useState(false)
  const [character, setCharacter] = useState(null)
  const [charChecked, setCharChecked] = useState(false)

  // Try stored passphrase on load
  useEffect(() => {
    if (!getPassphrase()) { setChecked(true); return }
    api.me()
      .then(setUser)
      .catch(() => clearPassphrase())
      .finally(() => setChecked(true))
  }, [])

  // Load character once logged in
  useEffect(() => {
    if (!user) return
    api.character()
      .then((c) => setCharacter(c && c.name ? c : null))
      .finally(() => setCharChecked(true))
  }, [user])

  const handleLogin = async (passphrase) => {
    setPassphrase(passphrase)
    try {
      const u = await api.login(passphrase)
      setUser(u)
    } catch (e) {
      clearPassphrase()
      throw e
    }
  }

  if (!checked) return null
  if (!user) return <Login onLogin={handleLogin} />
  if (!charChecked) return null
  if (!character) {
    return <CharacterCreate onCreated={setCharacter} userName={user.name} />
  }

  return <Table user={user} character={character} setCharacter={setCharacter} />
}

function Table({ user, character, setCharacter }) {
  const [party, setParty] = useState([])
  const [online, setOnline] = useState([])
  const [feed, setFeed] = useState([])
  const [thinking, setThinking] = useState(null)
  const [mobilePanel, setMobilePanel] = useState(null)

  // Initial data
  useEffect(() => {
    api.party().then(setParty).catch(() => {})
    api.feed().then((rows) => {
      setFeed(rows.map((r) => historyToEvent(r)))
    }).catch(() => {})
  }, [])

  const refreshMyCharacter = useCallback(() => {
    api.character().then((c) => c && c.name && setCharacter(c)).catch(() => {})
  }, [setCharacter])

  useGameSocket((type, payload) => {
    switch (type) {
      case 'presence':
        setOnline(payload.online)
        break
      case 'player_action':
        setFeed((f) => [...f, { kind: 'player', ...payload }])
        break
      case 'gm_narration':
        setFeed((f) => [...f, { kind: 'gm', author: payload.author, content: payload.content }])
        break
      case 'gm_thinking':
        setThinking(payload.acting_player)
        break
      case 'gm_thinking_done':
        setThinking(null)
        break
      case 'dice_roll':
        setFeed((f) => [...f, { kind: 'roll', ...payload }])
        break
      case 'system_message':
        setFeed((f) => [...f, { kind: 'system', content: payload.content }])
        break
      case 'party_update':
        setParty(payload.party)
        refreshMyCharacter()
        break
      default:
        break
    }
  })

  return (
    <div className="shell">
      <header className="header">
        <h1>
          The Borderlands Table
          <span className="sub">B/X · Old-School Essentials</span>
        </h1>
        <div className="presence">
          {online.map((name) => (
            <span key={name} className="who">
              <span className="dot" style={{ background: '#7ef7a0' }} />
              {name}
            </span>
          ))}
        </div>
      </header>

      <PartyPanel
        party={party}
        user={user}
        className={mobilePanel === 'party' ? 'mobile-open' : ''}
      />

      <GameView
        feed={feed}
        thinking={thinking}
        user={user}
        character={character}
      />

      <CharacterSheet
        character={character}
        setCharacter={setCharacter}
        className={mobilePanel === 'sheet' ? 'mobile-open' : ''}
      />

      <nav className="mobile-tabs">
        <button onClick={() => setMobilePanel(mobilePanel === 'party' ? null : 'party')}>
          Party
        </button>
        <button onClick={() => setMobilePanel(null)}>Table</button>
        <button onClick={() => setMobilePanel(mobilePanel === 'sheet' ? null : 'sheet')}>
          Sheet
        </button>
      </nav>
    </div>
  )
}

function historyToEvent(row) {
  if (row.role === 'assistant') return { kind: 'gm', author: row.author || 'GM', content: row.content }
  if (row.role === 'system') return { kind: 'system', content: row.content }
  return { kind: 'player', author: row.author, content: row.content }
}
