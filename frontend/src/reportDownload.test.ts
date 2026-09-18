import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const api = readFileSync(new URL('./api.ts', import.meta.url), 'utf8')
const panel = readFileSync(new URL('./components/OperationalTripPanel.tsx', import.meta.url), 'utf8')

test('trip report is downloaded as a validated PDF blob', () => {
  assert.match(api, /response\.blob\(\)/)
  assert.match(api, /application\/pdf/)
  assert.match(api, /signature !== '%PDF-'/)
  assert.match(api, /anchor\.download/)
  assert.match(api, /document\.body\.appendChild\(anchor\)/)
  assert.match(api, /anchor\.remove\(\)/)
  assert.match(api, /URL\.revokeObjectURL\(url\)/)
  assert.match(api, /controller\.abort\(\)/)
  assert.doesNotMatch(api, /report\.json/)
})

test('report button blocks repeated clicks and presents backend errors', () => {
  assert.match(panel, /if \(reportPending\) return/)
  assert.match(panel, /disabled=\{reportPending\}/)
  assert.match(panel, /reportError/)
  assert.match(panel, /Baixar relatório PDF/)
})
