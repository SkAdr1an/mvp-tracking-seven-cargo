import assert from 'node:assert/strict'
import test from 'node:test'
import { currentDeviationDriverIds } from './overviewMetrics.ts'
import type { Driver, RoutePaths } from './types.ts'

test('off-route count ignores historical deviations from inactive trips and reused plates', () => {
  const drivers = [
    { id: 'AAA1A11', trip_id: 'current-1', operational: { trip_key: 'trafegus:current-1' } },
    { id: 'BBB2B22', trip_id: 'current-2', operational: { trip_key: 'trafegus:current-2' } },
  ] as Driver[]
  const paths = { paths: [
    { trip_key: 'trafegus:old-1', plate: 'AAA1A11', segments: [], deviation: { status: 'ACTIVE' } },
    { trip_key: 'trafegus:current-2', plate: 'BBB2B22', segments: [], deviation: { status: 'ACTIVE' } },
    { trip_key: 'trafegus:old-2', plate: 'CCC3C33', segments: [], deviation: { status: 'ACTIVE' } },
  ] } as RoutePaths

  assert.deepEqual([...currentDeviationDriverIds(drivers, paths)], ['BBB2B22'])
})

test('off-route count requires an active confirmed deviation', () => {
  const drivers = [{ id: 'AAA1A11', trip_id: '123' }] as Driver[]
  const returned = { paths: [{ trip_key: 'trafegus:123', plate: 'AAA1A11', segments: [], deviation: { status: 'RETURNED' } }] } as RoutePaths

  assert.equal(currentDeviationDriverIds(drivers, returned).size, 0)
})

