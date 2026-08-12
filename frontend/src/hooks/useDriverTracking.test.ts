import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const hook = readFileSync(new URL('./useDriverTracking.ts', import.meta.url), 'utf8')
const api = readFileSync(new URL('../api.ts', import.meta.url), 'utf8')

test('tracking hook obtains the manager socket URL from the shared API configuration', () => {
  assert.match(hook, /new WebSocket\(trackingSocketUrl\(\)\)/)
  assert.doesNotMatch(hook, /ws:\/\/localhost/)
  assert.match(api, /import\.meta\.env\.VITE_WS_URL/)
  assert.match(api, /window\.location\.protocol === 'https:' \? 'wss:' : 'ws:'/)
  assert.match(api, /\/\/\$\{window\.location\.host\}/)
  assert.match(api, /import\.meta\.env\.DEV \? 'http:\/\/localhost:8000' : ''/)
  assert.match(api, /\/tracking\/ws\/manager/)
})

test('tracking hook defers StrictMode connection and safely disposes a connecting socket', () => {
  assert.match(hook, /scheduleConnection\(0\)/)
  assert.match(hook, /readyState === WebSocket\.CONNECTING/)
  assert.match(hook, /onopen = \(\) => currentSocket\.close/)
})

test('tracking hook reconnects once with bounded exponential backoff', () => {
  assert.match(hook, /Math\.min\(1000 \* 2 \*\* attempts, 15_000\)/)
  assert.match(hook, /window\.clearTimeout\(retryTimer\)/)
  assert.match(hook, /setConnectionGeneration/)
})
