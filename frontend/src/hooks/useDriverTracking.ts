import { useCallback, useEffect, useRef, useState } from 'react'
import { trackingSocketUrl } from '../api'
import type { Driver, DriverStatus } from '../types'

type ConnectionState = 'connecting' | 'connected' | 'disconnected'

interface InitialMessage {
  type: 'initial_drivers'
  drivers: Record<string, Omit<Driver, 'id'>>
}

interface UpdateMessage {
  type: 'driver_update'
  driver_id: string
  location: Driver['location']
  status: DriverStatus
  timestamp: string
}

export function useDriverTracking() {
  const [drivers, setDrivers] = useState<Record<string, Driver>>({})
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [connectionGeneration, setConnectionGeneration] = useState(0)
  const mountedRef = useRef(false)

  const reconnect = useCallback(() => {
    if (mountedRef.current) setConnectionGeneration((current) => current + 1)
  }, [])

  useEffect(() => {
    let active = true
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let attempts = 0

    mountedRef.current = true

    const scheduleConnection = (delay: number) => {
      window.clearTimeout(retryTimer)
      retryTimer = window.setTimeout(connect, delay)
    }

    function connect() {
      if (!active) return
      setConnection('connecting')
      socket = new WebSocket(trackingSocketUrl())
      const currentSocket = socket

      currentSocket.onopen = () => {
        if (!active || socket !== currentSocket) return
        attempts = 0
        setConnection('connected')
      }
      currentSocket.onmessage = (event) => {
        if (!active || socket !== currentSocket) return
        try {
          const message = JSON.parse(event.data) as InitialMessage | UpdateMessage
          if (message.type === 'initial_drivers') {
            const normalized = Object.fromEntries(
              Object.entries(message.drivers).map(([id, driver]) => [id, { id, ...driver }]),
            )
            setDrivers(normalized)
          } else if (message.type === 'driver_update') {
            setDrivers((current) => ({
              ...current,
              [message.driver_id]: {
                id: message.driver_id,
                status: message.status,
                location: message.location,
                last_update: message.timestamp,
              },
            }))
          }
        } catch {
          // Ignora mensagens desconhecidas sem derrubar o canal de rastreamento.
        }
      }
      currentSocket.onerror = () => {
        if (active && socket === currentSocket) setConnection('disconnected')
      }
      currentSocket.onclose = () => {
        if (!active || socket !== currentSocket) return
        socket = null
        setConnection('disconnected')
        attempts += 1
        scheduleConnection(Math.min(1000 * 2 ** attempts, 15_000))
      }
    }

    // Evita criar um socket no primeiro ciclo descartável do StrictMode.
    scheduleConnection(0)

    return () => {
      active = false
      mountedRef.current = false
      window.clearTimeout(retryTimer)
      const currentSocket = socket
      socket = null
      if (!currentSocket) return
      currentSocket.onmessage = null
      currentSocket.onerror = null
      currentSocket.onclose = null
      if (currentSocket.readyState === WebSocket.CONNECTING) {
        currentSocket.onopen = () => currentSocket.close(1000, 'Component unmounted')
      } else if (currentSocket.readyState === WebSocket.OPEN) {
        currentSocket.close(1000, 'Component unmounted')
      }
    }
  }, [connectionGeneration])

  return { drivers: Object.values(drivers), connection, reconnect }
}
