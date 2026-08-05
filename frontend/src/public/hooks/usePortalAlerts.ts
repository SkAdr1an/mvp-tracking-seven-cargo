import { useEffect, useState } from 'react'
import { fetchPortalAlerts } from '../api'
import type { PortalAlertsResponse } from '../types'
import { isVisualDemo, VISUAL_DEMO_POSITION_EVENT, visualDemoAlerts } from '../visualDemo'

export function usePortalAlerts(token: string, enabled: boolean) {
  const demo = isVisualDemo(token)
  const [data, setData] = useState<PortalAlertsResponse | undefined>(() => demo ? visualDemoAlerts() : undefined)
  const [degraded, setDegraded] = useState(false)
  useEffect(() => {
    if (demo) {
      const update = () => { setData(visualDemoAlerts()); setDegraded(false) }
      update(); window.addEventListener(VISUAL_DEMO_POSITION_EVENT, update)
      return () => window.removeEventListener(VISUAL_DEMO_POSITION_EVENT, update)
    }
    if (!enabled) { setData(undefined); setDegraded(false); return }
    let active = true
    const controller = new AbortController()
    const refresh = () => void fetchPortalAlerts(token, controller.signal)
      .then((value) => { if (active) { setData(value); setDegraded(false) } })
      .catch(() => { if (active) setDegraded(true) })
    refresh()
    const interval = window.setInterval(refresh, 60_000)
    return () => { active = false; controller.abort(); window.clearInterval(interval) }
  }, [demo, enabled, token])
  return { data, degraded }
}
