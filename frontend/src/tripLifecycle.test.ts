import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const panel=readFileSync(new URL('./components/OperationalTripPanel.tsx',import.meta.url),'utf8')
const api=readFileSync(new URL('./api.ts',import.meta.url),'utf8')

test('cancel and archive controls use explicit permissions and confirmation dialog',()=>{
  assert.match(panel,/usePermission\('trips:cancel'\)/)
  assert.match(panel,/usePermission\('trips:archive'\)/)
  assert.match(panel,/kind:'lifecycle',action:'cancel'/)
  assert.match(panel,/kind:'lifecycle',action:'archive'/)
  assert.match(panel,/kind:'lifecycle',action:'unarchive'/)
  assert.match(panel,/Motivo \/ justificativa/)
})

test('lifecycle mutations use only their dedicated backend endpoints',()=>{
  assert.match(api,/tripLifecycle:/)
  assert.match(api,/operations\/trips\/\$\{encodeURIComponent\(tripKey\)\}\/\$\{action\}/)
  const lifecycle=api.slice(api.indexOf('tripLifecycle:'),api.indexOf('returnDecision:'))
  assert.doesNotMatch(lifecycle,/DELETE/)
})
