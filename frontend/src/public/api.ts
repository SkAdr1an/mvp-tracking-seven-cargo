import type { PortalAlertsResponse, PublicTrip } from './types'
import { PublicTripApiError, type PublicTripFailureReason } from './errors'

const API_URL = (import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '')).replace(/\/$/, '')

export async function fetchPublicTrip(token: string, signal?: AbortSignal): Promise<PublicTrip> {
  const response = await fetch(`${API_URL}/api/public/trips/${encodeURIComponent(token)}`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
    signal,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      detail?: string
      reason?: PublicTripFailureReason
    } | null
    const message = payload?.detail || (
      response.status >= 500
        ? 'Não foi possível acessar a Central Seven Cargo.'
        : 'Não foi possível atualizar a viagem.'
    )
    throw new PublicTripApiError(response.status, message, payload?.reason)
  }
  return response.json() as Promise<PublicTrip>
}

export async function sendMobilePosition(token: string, position: GeolocationPosition): Promise<void> {
  const response = await fetch(`${API_URL}/api/public/trips/${encodeURIComponent(token)}/positions`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      accuracy_m: position.coords.accuracy,
      recorded_at: new Date(position.timestamp).toISOString(),
    }),
    cache: 'no-store',
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail || 'Não foi possível enviar a localização.')
  }
}

export async function fetchPortalAlerts(token: string, signal?: AbortSignal): Promise<PortalAlertsResponse> {
  const response = await fetch(`${API_URL}/api/public/trips/${encodeURIComponent(token)}/alerts`, {
    headers: { Accept: 'application/json' }, cache: 'no-store', credentials: 'omit',
    referrerPolicy: 'no-referrer', signal,
  })
  if (!response.ok) throw new Error('Alertas temporariamente indisponíveis.')
  return response.json() as Promise<PortalAlertsResponse>
}
