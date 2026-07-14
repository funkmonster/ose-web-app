import { useEffect, useRef } from 'react'
import { getPassphrase } from '../api'

// Subscribes to the game event stream. `onEvent(type, payload)` fires for every event.
export function useGameSocket(onEvent) {
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  useEffect(() => {
    let ws = null
    let closed = false
    let retryTimer = null
    let pingTimer = null

    function connect() {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${proto}://${window.location.host}/ws?passphrase=${encodeURIComponent(getPassphrase())}`
      ws = new WebSocket(url)

      ws.onopen = () => {
        // keepalive so proxies don't drop the connection
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 25000)
      }

      ws.onmessage = (e) => {
        try {
          const { type, payload } = JSON.parse(e.data)
          handlerRef.current(type, payload)
        } catch {
          /* ignore malformed frames */
        }
      }

      ws.onclose = () => {
        clearInterval(pingTimer)
        if (!closed) retryTimer = setTimeout(connect, 2000)
      }
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      clearInterval(pingTimer)
      if (ws) ws.close()
    }
  }, [])
}
