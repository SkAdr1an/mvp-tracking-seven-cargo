import type { CachedPublicTrip, PublicTrip } from './types'
import type { PublicTripFailureReason } from './errors'

export interface PublicTripCache {
  read(token: string): Promise<CachedPublicTrip | undefined>
  save(token: string, data: PublicTrip, synchronizedAt: string): Promise<CachedPublicTrip>
  clear(token: string): Promise<void>
}

export type SyncResult =
  | { kind: 'fresh'; record: CachedPublicTrip }
  | { kind: 'cached'; record?: CachedPublicTrip; error: string }
  | { kind: 'invalid'; error: string; reason: PublicTripFailureReason }

export async function synchronizePublicTrip(
  token: string,
  fetchTrip: (token: string) => Promise<PublicTrip>,
  cache: PublicTripCache,
): Promise<SyncResult> {
  let cached: CachedPublicTrip | undefined
  try {
    cached = await cache.read(token)
  } catch {
    cached = undefined
  }
  try {
    const data = await fetchTrip(token)
    const synchronizedAt = new Date().toISOString()
    const record = { key: '', data, synchronizedAt }
    try {
      return { kind: 'fresh', record: await cache.save(token, data, synchronizedAt) }
    } catch {
      return { kind: 'fresh', record }
    }
  } catch (error) {
    if (isTerminalLinkError(error)) {
      try {
        await cache.clear(token)
      } catch {
        // The server decision remains authoritative even if local storage is unavailable.
      }
      return {
        kind: 'invalid',
        error: error.message,
        reason: error.reason || 'invalid_token',
      }
    }
    return {
      kind: 'cached',
      record: cached,
      error: error instanceof Error ? error.message : 'Não foi possível atualizar a viagem.',
    }
  }
}

function isHttpStatus(error: unknown, status: number): error is Error & { status: number } {
  return error instanceof Error && 'status' in error && error.status === status
}

function isTerminalLinkError(
  error: unknown,
): error is Error & { status: number; reason?: PublicTripFailureReason } {
  return isHttpStatus(error, 404) || isHttpStatus(error, 410)
}
