import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const app = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8')
const api = readFileSync(new URL('./api.ts', import.meta.url), 'utf8')

test('operational hooks mount only after a valid panel session', () => {
  assert.match(app, /api\.panelMe\(\)/)
  assert.match(app, /if \(session === null\) return <PanelLogin/)
  assert.match(app, /return <AuthenticatedApp session=/)
  assert.match(app, /function AuthenticatedApp[\s\S]*useFleetTracking\(\)/)
})

test('all panel and operational HTTP requests include the HttpOnly session cookie', () => {
  assert.match(api, /credentials: 'include'/)
  assert.doesNotMatch(api, /VITE_TRACKING_TOKEN/)
})

test('login errors do not expose backend details', () => {
  assert.match(app, /Não foi possível entrar\. Verifique as credenciais ou tente novamente mais tarde\./)
})
