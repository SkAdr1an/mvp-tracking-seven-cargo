import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const mapSource = readFileSync(new URL('./DriverMap.tsx', import.meta.url), 'utf8')

test('planned route rendering is provider-neutral for TomTom and ORS geometry', () => {
  assert.match(mapSource, /traffic\?\.routes\.map/)
  assert.match(mapSource, /route\.geometry\.map/)
  assert.match(mapSource, /key=\{route\.id\}/)
  assert.doesNotMatch(mapSource, /geometry_provider\s*===/)
  assert.doesNotMatch(mapSource, /provider\s*===\s*['"](?:tomtom|openrouteservice)/i)
})

test('route identity replaces the polyline without provider-specific duplication', () => {
  const plannedPolylineCount = (mapSource.match(/<Polyline key=\{route\.id\}/g) || []).length
  assert.equal(plannedPolylineCount, 1)
})

test('no driver timer or provider badge was introduced', () => {
  assert.doesNotMatch(mapSource, /setInterval|cron[oô]metro|geometry_provider|openrouteservice/i)
})
