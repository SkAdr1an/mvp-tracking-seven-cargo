import assert from 'node:assert/strict'
import test from 'node:test'
import { alertVisual, isValidCoordinate, mapPriorityCoordinates, routeDistanceStats, splitRouteAtPosition } from './publicMapUtils.ts'
import type { PublicTrip } from './types.ts'

const base = {
  driver_name: 'Teste', route: { origin: { name: 'Origem', coordinate: null }, destination: { name: 'Destino', coordinate: null }, geometry: [], important_points: [] },
  public_status: '', last_updated_at: '', stale: false, finished: false, vehicle: { plate: 'ABC1D23' }, location_sources: { situation: 'UNAVAILABLE' }, mobile_location_enabled: false, portal_alerts_enabled: false, operational_instructions: [], central_contact: { name: 'Central' }, notices: [],
} as PublicTrip

test('zero, missing, non-finite and out-of-range coordinates are unavailable', () => {
  assert.equal(isValidCoordinate({ latitude: 0, longitude: 0 }), false)
  assert.equal(isValidCoordinate(null), false)
  assert.equal(isValidCoordinate({ latitude: 91, longitude: -44 }), false)
  assert.equal(isValidCoordinate({ latitude: Number.NaN, longitude: -44 }), false)
  assert.equal(isValidCoordinate({ latitude: -19.9, longitude: -44.1 }), true)
})

test('map framing prioritizes vehicle with route, endpoints, then one valid position', () => {
  const endpoints = { ...base, route: { ...base.route, origin: { name: 'O', coordinate: { latitude: -20, longitude: -44 } }, destination: { name: 'D', coordinate: { latitude: -19, longitude: -43 } } } }
  assert.equal(mapPriorityCoordinates(endpoints).length, 2)
  const one = { ...base, latest_position: { latitude: -19.9, longitude: -44, recorded_at: '', source: 'Rastreador' } }
  assert.deepEqual(mapPriorityCoordinates(one), [one.latest_position])
  assert.deepEqual(mapPriorityCoordinates(base), [])
})

test('route is split into travelled and remaining sections near vehicle', () => {
  const geometry = [{ latitude: -20, longitude: -44 }, { latitude: -19.9, longitude: -43.9 }, { latitude: -19.8, longitude: -43.8 }]
  const split = splitRouteAtPosition(geometry, { latitude: -19.91, longitude: -43.91 })
  assert.equal(split.travelled.length, 2)
  assert.equal(split.remaining.length, 2)
  const distances = routeDistanceStats(geometry, { latitude: -19.91, longitude: -43.91 })
  assert.ok(distances.travelledKm > 0)
  assert.ok(distances.remainingKm > 0)
})

test('traffic, rain, accident, blockage and deviation have distinct visuals and severity', () => {
  const types = ['TRANSITO_LENTO', 'CHUVA_FORTE', 'ACIDENTE', 'BLOQUEIO', 'DESVIO_CONFIRMADO', 'CLIMA_NORMAL']
  const visuals = types.map((type) => alertVisual({ type, severity: type === 'BLOQUEIO' ? 'CRITICO' : 'ATENCAO' } as never))
  assert.equal(new Set(visuals.map((item) => item.className.split(' ')[0])).size, 6)
  assert.match(visuals[3].className, /critical/)
})
