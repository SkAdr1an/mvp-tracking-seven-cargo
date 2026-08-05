import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchPublicTrip } from '../api'
import { clearTripCache, readTripCache, saveTripCache } from '../storage/tripCache'
import { synchronizePublicTrip } from '../sync'
import type { CachedPublicTrip } from '../types'
import type { PublicTripFailureReason } from '../errors'
import { isVisualDemo, visualDemoTrip } from '../visualDemo'

const cache = { read: readTripCache, save: saveTripCache, clear: clearTripCache }

export function usePublicTrip(token: string) {
  const demo = isVisualDemo(token)
  const [record, setRecord] = useState<CachedPublicTrip | undefined>(() => demo ? { key: token, data: visualDemoTrip(), synchronizedAt: new Date().toISOString() } : undefined)
  const [online, setOnline] = useState(() => navigator.onLine)
  const [loading, setLoading] = useState(!demo)
  const [refreshing, setRefreshing] = useState(false)
  const [invalid, setInvalid] = useState(false)
  const [terminalReason, setTerminalReason] = useState<PublicTripFailureReason>()
  const [error, setError] = useState<string>()
  const mounted = useRef(true)
  const activeToken = useRef(token)
  const requestSequence = useRef(0)
  activeToken.current = token

  const refresh = useCallback(async () => {
    if (!mounted.current) return
    if (demo) {
      setRecord({ key: token, data: visualDemoTrip(), synchronizedAt: new Date().toISOString() })
      return
    }
    const requestToken = token
    const sequence = ++requestSequence.current
    setRefreshing(true)
    const result = await synchronizePublicTrip(requestToken, fetchPublicTrip, cache)
    if (
      !mounted.current
      || activeToken.current !== requestToken
      || requestSequence.current !== sequence
    ) return
    if (result.kind === 'fresh') {
      setRecord(result.record)
      setInvalid(false)
      setTerminalReason(undefined)
      setError(undefined)
    } else if (result.kind === 'invalid') {
      setRecord(undefined)
      setInvalid(true)
      setTerminalReason(result.reason)
      setError(result.error)
    } else {
      if (result.record) setRecord(result.record)
      setError(result.error)
    }
    setLoading(false)
    setRefreshing(false)
  }, [demo, token])

  useEffect(() => {
    if (demo) {
      setRecord({ key: token, data: visualDemoTrip(), synchronizedAt: new Date().toISOString() })
      setLoading(false)
      return
    }
    mounted.current = true
    activeToken.current = token
    requestSequence.current += 1
    setRecord(undefined)
    setInvalid(false)
    setTerminalReason(undefined)
    setError(undefined)
    setLoading(true)
    setRefreshing(false)
    let cancelled = false
    void readCacheWithTimeout(token).then((cached) => {
      if (!cancelled && cached) setRecord(cached)
    }).catch(() => undefined).finally(() => {
      if (cancelled) return
      if (navigator.onLine) void refresh()
      else setLoading(false)
    })
    const onOnline = () => {
      setOnline(true)
      void refresh()
    }
    const onOffline = () => setOnline(false)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    const interval = window.setInterval(() => {
      if (navigator.onLine) void refresh()
    }, 60_000)
    return () => {
      cancelled = true
      requestSequence.current += 1
      mounted.current = false
      window.clearInterval(interval)
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [demo, refresh, token])

  return { record, online, loading, refreshing, invalid, terminalReason, error, refresh }
}

async function readCacheWithTimeout(token: string): Promise<CachedPublicTrip | undefined> {
  return Promise.race([
    readTripCache(token),
    new Promise<undefined>((resolve) => window.setTimeout(() => resolve(undefined), 800)),
  ])
}
