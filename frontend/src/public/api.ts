import type { PublicTrip } from './types'
import { PublicTripApiError, type PublicTripFailureReason } from './errors'

const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

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
