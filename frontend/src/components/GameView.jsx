import React, { useState, useRef, useEffect } from 'react'
import { api } from '../api'

const QUICK_DICE = ['1d20', '1d6', '2d6', '3d6', '1d8', '1d4', '1d100']

export default function GameView({ feed, thinking, user, character, physicalDiceMode }) {
  const [action, setAction] = useState('')
  const [customDie, setCustomDie] = useState('')
  const [reportNotation, setReportNotation] = useState('')
  const [reportResult, setReportResult] = useState('')
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(null) // {title, content}
  const [error, setError] = useState('')
  const bottomRef = useRef(null)
  const feedRef = useRef(null)

  // Auto-scroll if user is near the bottom
  useEffect(() => {
    const el = feedRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [feed, thinking])

  const sendAction = async () => {
    const text = action.trim()
    if (!text || busy) return
    setBusy(true)
    setError('')
    setAction('')
    try {
      await api.play(text)
    } catch (e) {
      setError(e.message)
      setAction(text) // give it back so they can retry
    } finally {
      setBusy(false)
    }
  }

  const rollDie = async (notation) => {
    try {
      await api.roll(notation, '')
    } catch (e) {
      setError(e.message)
    }
  }

  const reportRoll = async () => {
    const notation = reportNotation.trim()
    if (!notation || reportResult === '') return
    try {
      await api.roll(notation, '', Number(reportResult))
      setReportNotation('')
      setReportResult('')
    } catch (e) {
      setError(e.message)
    }
  }

  const showRecap = async () => {
    setModal({ title: 'Session Recap', content: 'The chronicler consults the record…' })
    try {
      const { recap } = await api.recap()
      setModal({ title: 'Session Recap', content: recap })
    } catch (e) {
      setModal({ title: 'Session Recap', content: `Unavailable: ${e.message}` })
    }
  }

  const showSummary = async () => {
    setModal({ title: 'Campaign Memory', content: 'Opening the chronicle…' })
    try {
      const s = await api.summary()
      const body = s.summary
        ? `${s.summary}\n\n— ${s.action_count} actions chronicled; next update in ${s.summarize_every - (s.action_count % s.summarize_every)}.`
        : `Nothing chronicled yet. A summary forms every ${s.summarize_every} actions.`
      setModal({ title: 'Campaign Memory', content: body })
    } catch (e) {
      setModal({ title: 'Campaign Memory', content: `Unavailable: ${e.message}` })
    }
  }

  const startCampaign = async () => {
    const name = window.prompt('Campaign name?', 'Keep on the Borderlands')
    if (!name) return
    const module = window.prompt('Module or setting?', 'B2: Keep on the Borderlands')
    if (!module) return
    setBusy(true)
    try {
      await api.startCampaign(name, module)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const longRest = async () => {
    try { await api.rest('long') } catch (e) { setError(e.message) }
  }

  return (
    <div className="feed-area">
      <div className="feed" ref={feedRef}>
        {feed.length === 0 && !thinking && (
          <div className="msg-system">
            The table is set. No campaign yet — begin one below.
          </div>
        )}
        {feed.map((ev, i) => <FeedEvent key={i} ev={ev} />)}
        {thinking && (
          <div className="gm-thinking">
            The GM considers {thinking === user.name ? 'your' : `${thinking}'s`} action
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="input-bar">
        {error && (
          <div className="msg-system" style={{ color: 'var(--magenta)', marginBottom: 6 }}>
            {error}
          </div>
        )}
        <div className="input-row">
          <textarea
            placeholder={`What does ${character.name} do?`}
            value={action}
            onChange={(e) => setAction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendAction()
              }
            }}
            disabled={busy}
          />
          <button onClick={sendAction} disabled={busy || !action.trim()}>
            {busy ? '…' : 'Act'}
          </button>
        </div>
        <div className="dice-row">
          {physicalDiceMode ? (
            <>
              <input
                placeholder="notation, e.g. 1d20"
                value={reportNotation}
                onChange={(e) => setReportNotation(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') reportRoll() }}
              />
              <input
                type="number"
                placeholder="result"
                value={reportResult}
                onChange={(e) => setReportResult(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') reportRoll() }}
              />
              <button
                className="chip"
                onClick={reportRoll}
                disabled={!reportNotation.trim() || reportResult === ''}
              >
                🎲 Report Roll
              </button>
            </>
          ) : (
            <>
              {QUICK_DICE.map((d) => (
                <button key={d} className="chip" onClick={() => rollDie(d)}>{d}</button>
              ))}
              <input
                placeholder="2d4+1"
                value={customDie}
                onChange={(e) => setCustomDie(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && customDie.trim()) {
                    rollDie(customDie.trim())
                    setCustomDie('')
                  }
                }}
              />
            </>
          )}
          <span style={{ flex: 1 }} />
          <button className="chip" onClick={showRecap}>Recap</button>
          <button className="chip" onClick={showSummary}>Memory</button>
          <button className="chip" onClick={longRest}>Long rest</button>
          <button className="chip" onClick={startCampaign}>New campaign</button>
        </div>
      </div>

      {modal && (
        <div className="modal-veil" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{modal.title}</h2>
            <MD text={modal.content} />
            <div className="close-row">
              <button onClick={() => setModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Lightweight markdown renderer — handles bold, italic, and line breaks.
// Keeps the typewriter aesthetic without pulling in a full library.
function MD({ text }) {
  if (!text) return null
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>
          {i > 0 && <br />}
          {renderInline(line)}
        </span>
      ))}
    </>
  )
}

function renderInline(text) {
  // Split on **bold**, *italic*, handling them in order
  const parts = []
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*)/g
  let last = 0, m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[0].startsWith('**')) {
      parts.push(<strong key={m.index}>{m[2]}</strong>)
    } else {
      parts.push(<em key={m.index}>{m[3]}</em>)
    }
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function FeedEvent({ ev }) {
  switch (ev.kind) {
    case 'gm':
      return (
        <div className="msg-gm" data-author={ev.author || 'GM'}>
          <MD text={ev.content} />
        </div>
      )
    case 'player':
      return (
        <div className="msg-player" style={{ '--player-color': ev.color }}>
          <div className="who">{ev.author}</div>
          <div className="what">{ev.content}</div>
        </div>
      )
    case 'roll':
      return (
        <div className={`msg-roll ${ev.physical ? 'physical' : ''}`} style={{ '--player-color': ev.color }}>
          <span className="die">{ev.total}</span>
          <span>
            <span className="who">{ev.author}</span>
            {' '}{ev.physical ? 'reported' : 'rolled'} {ev.notation}
            {ev.rolls?.length > 1 && ` [${ev.rolls.join(', ')}]`}
            {ev.reason && ` — ${ev.reason}`}
            {ev.physical && <span className="physical-badge"> 🎲 physical</span>}
          </span>
        </div>
      )
    case 'system':
      return <div className="msg-system">{ev.content}</div>
    default:
      return null
  }
}
