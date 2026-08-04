import { useEffect, useState } from 'react'
import { fetchPortalAlerts } from '../api'
import type { PortalAlertsResponse } from '../types'

export function usePortalAlerts(token: string, enabled: boolean) {
  const [data, setData] = useState<PortalAlertsResponse>()
  const [degraded, setDegraded] = useState(false)
  useEffect(() => {
    if (!enabled) { setData(undefined); setDegraded(false); return }
    let active = true
    const controller = new AbortController()
    const refresh = () => void fetchPortalAlerts(token, controller.signal)
      .then((value) => { if (active) { setData(value); setDegraded(false) } })
      .catch(() => { if (active) setDegraded(true) })
    refresh()
    const interval = window.setInterval(refresh, 60_000)
    return () => { active = false; controller.abort(); window.clearInterval(interval) }
  }, [enabled, token])
  return { data, degraded }
}
