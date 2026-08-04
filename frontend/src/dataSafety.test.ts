import assert from 'node:assert/strict'
import test from 'node:test'
import { finiteNumber, sanitizedErrorContext, validCoordinates, validDate } from './dataSafety.ts'

test('coordinates reject null, non-finite and out-of-range values', () => {
  assert.equal(validCoordinates(null, -44), false)
  assert.equal(validCoordinates(Number.NaN, -44), false)
  assert.equal(validCoordinates(-23, Number.POSITIVE_INFINITY), false)
  assert.equal(validCoordinates(91, -44), false)
  assert.equal(validCoordinates(-23, -181), false)
  assert.equal(validCoordinates(-23, -44), true)
})

test('dates and numeric fields degrade without invented values', () => {
  assert.equal(validDate('not-a-date'), undefined)
  assert.equal(validDate('2026-07-30T10:00:00Z'), '2026-07-30T10:00:00Z')
  assert.equal(finiteNumber(undefined), undefined)
  assert.equal(finiteNumber(Number.NaN), undefined)
})

test('error context is bounded and redacts sensitive assignments', () => {
  const result = sanitizedErrorContext(new Error('token=secret https://internal.example/trip'))
  assert.equal(result.name, 'Error')
  assert.doesNotMatch(result.message, /secret|internal\.example/)
})
