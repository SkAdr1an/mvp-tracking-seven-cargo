import assert from 'node:assert/strict'
import test from 'node:test'
import { PublicTripApiError } from './errors.ts'
import { synchronizePublicTrip, type PublicTripCache } from './sync.ts'
import type { CachedPublicTrip, PublicTrip } from './types.ts'

const trip = (driver: string): PublicTrip => ({
  driver_name: driver,
  route: {
    origin: { name: 'Betim/MG' },
    destination: { name: 'Jaboatão/PE' },
    geometry: [],
    important_points: [],
  },
  public_status: 'Em viagem',
  last_updated_at: '2026-07-27T15:00:00Z',
  stale: false,
  finished: false,
  vehicle: { plate: 'ABC1D23' },
  operational_instructions: [],
  central_contact: { name: 'Central Seven Cargo' },
  notices: [],
})

class MemoryCache implements PublicTripCache {
  records = new Map<string, CachedPublicTrip>()
  cleared: string[] = []

  async read(token: string) { return this.records.get(token) }
  async save(token: string, data: PublicTrip, synchronizedAt: string) {
    const record = { key: `fingerprint:${token}`, data, synchronizedAt }
    this.records.set(token, record)
    return record
  }
  async clear(token: string) {
    this.cleared.push(token)
    this.records.delete(token)
  }
}

test('online synchronization stores and returns the latest valid response', async () => {
  const cache = new MemoryCache()
  const result = await synchronizePublicTrip('token-a', async () => trip('João'), cache)
  assert.equal(result.kind, 'fresh')
  assert.equal(result.record?.data.driver_name, 'João')
  assert.equal(cache.records.get('token-a')?.data.driver_name, 'João')
})

test('offline synchronization preserves and returns the last valid response', async () => {
  const cache = new MemoryCache()
  await cache.save('token-a', trip('João'), '2026-07-27T15:01:00Z')
  const result = await synchronizePublicTrip('token-a', async () => {
    throw new TypeError('Failed to fetch')
  }, cache)
  assert.equal(result.kind, 'cached')
  assert.equal(result.record?.data.driver_name, 'João')
  assert.equal(cache.records.get('token-a')?.data.driver_name, 'João')
})

test('connection return automatically replaces stale cache with fresh data', async () => {
  const cache = new MemoryCache()
  await cache.save('token-a', trip('Versão offline'), '2026-07-27T15:01:00Z')
  const offline = await synchronizePublicTrip('token-a', async () => {
    throw new TypeError('offline')
  }, cache)
  assert.equal(offline.kind, 'cached')
  const reconnected = await synchronizePublicTrip('token-a', async () => trip('Versão atualizada'), cache)
  assert.equal(reconnected.kind, 'fresh')
  assert.equal(reconnected.record?.data.driver_name, 'Versão atualizada')
})

test('invalid token clears only its own cache and never exposes another trip', async () => {
  const cache = new MemoryCache()
  await cache.save('token-a', trip('Motorista A'), '2026-07-27T15:01:00Z')
  await cache.save('token-b', trip('Motorista B'), '2026-07-27T15:02:00Z')
  const result = await synchronizePublicTrip('token-a', async () => {
    throw new PublicTripApiError(404, 'Link de viagem inválido.', 'invalid_token')
  }, cache)
  assert.equal(result.kind, 'invalid')
  assert.deepEqual(cache.cleared, ['token-a'])
  assert.equal(cache.records.has('token-a'), false)
  assert.equal(cache.records.get('token-b')?.data.driver_name, 'Motorista B')
})

test('finished trip clears its own cache and keeps the terminal reason', async () => {
  const cache = new MemoryCache()
  await cache.save('token-a', trip('Motorista A'), '2026-07-27T15:01:00Z')
  const result = await synchronizePublicTrip('token-a', async () => {
    throw new PublicTripApiError(410, 'Viagem finalizada.', 'trip_finished')
  }, cache)
  assert.equal(result.kind, 'invalid')
  assert.equal(result.kind === 'invalid' ? result.reason : undefined, 'trip_finished')
  assert.deepEqual(cache.cleared, ['token-a'])
  assert.equal(cache.records.has('token-a'), false)
})

test('temporary API error never erases a previously synchronized trip', async () => {
  const cache = new MemoryCache()
  await cache.save('token-a', trip('Informação válida'), '2026-07-27T15:01:00Z')
  const result = await synchronizePublicTrip('token-a', async () => {
    throw new PublicTripApiError(503, 'Serviço indisponível')
  }, cache)
  assert.equal(result.kind, 'cached')
  assert.equal(cache.records.get('token-a')?.data.driver_name, 'Informação válida')
  assert.deepEqual(cache.cleared, [])
})
