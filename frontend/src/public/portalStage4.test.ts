import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const mobileHook = readFileSync(new URL('./hooks/useMobileLocation.ts', import.meta.url), 'utf8')
const alertsHook = readFileSync(new URL('./hooks/usePortalAlerts.ts', import.meta.url), 'utf8')
const styles = readFileSync(new URL('./public-trip.css', import.meta.url), 'utf8')

test('GPS denial and unavailability remain non-fatal', () => {
  assert.match(mobileHook, /PERMISSION_DENIED/)
  assert.match(mobileHook, /PERMISSION_DENIED \? 'denied' : 'unavailable'/)
  assert.match(mobileHook, /setStatus\('unavailable'\)/)
  assert.match(mobileHook, /portal continua funcionando sem o GPS/)
})

test('temporary internet failure preserves later polling opportunities', () => {
  assert.match(alertsHook, /setDegraded\(true\)/)
  assert.match(alertsHook, /setInterval\(refresh, 60_000\)/)
  assert.match(mobileHook, /sendMobilePosition[\s\S]*\.catch/)
  assert.match(mobileHook, /watchPosition/)
})

test('Android, iPhone and small mobile viewports use responsive safe layout', () => {
  assert.match(styles, /@media\s*\(max-width:\s*600px\)/)
  assert.match(styles, /@media\s*\(max-width:\s*380px\)/)
  assert.doesNotMatch(styles, /min-width:\s*[5-9]\d\dpx/)
})
