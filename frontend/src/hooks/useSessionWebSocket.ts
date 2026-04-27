import { useEffect, useRef, useState } from 'react'
import type { SessionEvent } from '../api/types'

function resolveWsBase(): string {
  const explicit = import.meta.env.VITE_WS_BASE as string | undefined
  if (explicit) return explicit.replace(/\/$/, '')

  const apiBase = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000'
  return apiBase.replace(/^http/i, 'ws')
}

export function useSessionWebSocket(
  sessionId: string,
  onEvent: (event: SessionEvent) => void,
) {
  const [connected, setConnected] = useState(false)
  const onEventRef = useRef(onEvent)

  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  useEffect(() => {
    if (!sessionId) return undefined

    let active = true
    let socket: WebSocket | null = null
    let reconnectTimer: number | null = null

    const connect = () => {
      if (!active) return
      socket = new WebSocket(`${resolveWsBase()}/ws/sessions/${sessionId}`)

      socket.onopen = () => {
        setConnected(true)
      }

      socket.onmessage = (message) => {
        try {
          const parsed = JSON.parse(message.data) as SessionEvent
          onEventRef.current(parsed)
        } catch {
          // Ignore malformed events.
        }
      }

      socket.onclose = () => {
        setConnected(false)
        if (!active) return
        reconnectTimer = window.setTimeout(connect, 1500)
      }

      socket.onerror = () => {
        socket?.close()
      }
    }

    connect()

    return () => {
      active = false
      setConnected(false)
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer)
      }
      socket?.close()
    }
  }, [sessionId])

  return { connected }
}