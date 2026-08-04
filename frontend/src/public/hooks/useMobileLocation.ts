import { useCallback, useEffect, useRef, useState } from 'react'
import { sendMobilePosition } from '../api'

export type MobileSharingState = 'idle' | 'consent' | 'sharing' | 'denied' | 'unavailable' | 'stopped' | 'error'

export function useMobileLocation(token: string, enabled: boolean) {
  const [status, setStatus] = useState<MobileSharingState>('idle')
  const [message, setMessage] = useState<string>()
  const watchId = useRef<number | undefined>(undefined)
  const lastSentAt = useRef(0)
  const active = useRef(true)

  const stop = useCallback(() => {
    if (watchId.current != null && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchId.current)
      watchId.current = undefined
    }
    if (active.current) setStatus('stopped')
  }, [])

  const requestConsent = useCallback(() => {
    if (enabled) setStatus('consent')
  }, [enabled])

  const start = useCallback(() => {
    if (!enabled || !navigator.geolocation) {
      setStatus('unavailable')
      setMessage('Este navegador não disponibilizou a localização.')
      return
    }
    setMessage(undefined)
    watchId.current = navigator.geolocation.watchPosition(
      (position) => {
        if (!active.current) return
        setStatus('sharing')
        const now = Date.now()
        if (now - lastSentAt.current < 15_000) return
        lastSentAt.current = now
        void sendMobilePosition(token, position).catch((error: unknown) => {
          if (!active.current) return
          setStatus('error')
          setMessage(error instanceof Error ? error.message : 'Falha temporária no envio.')
        })
      },
      (error) => {
        if (!active.current) return
        setStatus(error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable')
        setMessage(error.code === error.PERMISSION_DENIED
          ? 'Permissão recusada. O portal continua funcionando sem o GPS do celular.'
          : 'Não foi possível obter a localização deste aparelho.')
      },
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 },
    )
  }, [enabled, token])

  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      if (watchId.current != null && navigator.geolocation) navigator.geolocation.clearWatch(watchId.current)
    }
  }, [token])

  return { status, message, requestConsent, start, stop }
}
