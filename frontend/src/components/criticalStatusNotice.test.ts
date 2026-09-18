import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const notice = readFileSync(new URL('./CriticalStatusNotice.tsx', import.meta.url), 'utf8')
const overview = readFileSync(new URL('../pages/Overview.tsx', import.meta.url), 'utf8')

test('critical notice explains the delay using operational data', () => {
  assert.match(notice, /commitment_delta_minutes/)
  assert.match(notice, /Por que esta viagem está crítica\?/)
  assert.match(notice, /Compromisso:/)
  assert.match(notice, /Chegada prevista:/)
  assert.match(notice, /Fatores considerados:/)
  assert.match(notice, /Atraso justificado:/)
  assert.match(notice, /Responsabilidade:/)
})

test('critical notice is displayed in the selected trip information', () => {
  assert.match(overview, /<CriticalStatusNotice driver=\{focused\}/)
})
