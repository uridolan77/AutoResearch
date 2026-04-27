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
    let reconnectAttempts = 0

    const scheduleReconnect = () => {
      if (!active) return
      const baseMs = 500
      const cappedAttempt = Math.min(reconnectAttempts, 6)
      const backoffMs = Math.min(15_000, baseMs * 2 ** cappedAttempt)
      const jitterMs = Math.floor(Math.random() * 400)
      reconnectAttempts += 1
      reconnectTimer = window.setTimeout(connect, backoffMs + jitterMs)
    }

    const connect = () => {
      if (!active) return
      socket = new WebSocket(`${resolveWsBase()}/ws/sessions/${sessionId}`)

      socket.onopen = () => {
        setConnected(true)
        reconnectAttempts = 0
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
        scheduleReconnect()
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