import type { Driver, DriverStatus } from './types'

export const statusLabel = (status: DriverStatus) => ({
  online: 'Online', on_route: 'Em rota', paused: 'Parado', offline: 'Offline',
}[status])

export function formatAgo(date?: string): string {
  if (!date) return 'sem atualização'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(date).getTime()) / 1000))
  if (seconds < 60) return `há ${seconds}s`
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)}min`
  return `há ${Math.floor(seconds / 3600)}h`
}

export function isStale(driver: Driver): boolean {
  return !driver.last_update || Date.now() - new Date(driver.last_update).getTime() > 5 * 60_000
}

export const formatDuration = (minutes: number) => {
  const hours = Math.floor(minutes / 60)
  const remaining = Math.round(minutes % 60)
  return hours ? `${hours}h ${remaining}min` : `${remaining}min`
}
