import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { buildCentralWhatsAppUrl, locationAgeLabel } from './portalUtils.ts'

const app = readFileSync(new URL('./PublicTripApp.tsx', import.meta.url), 'utf8')
const sharing = readFileSync(new URL('./MobileLocationSharing.tsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('./public-trip.css', import.meta.url), 'utf8')

test('WhatsApp Central uses the approved number and a generic safe message', () => {
  const url = new URL(buildCentralWhatsAppUrl())
  assert.equal(`${url.origin}${url.pathname}`, 'https://wa.me/553584027743')
  assert.equal(url.searchParams.get('text'), 'Olá, Central Seven Cargo. Estou acessando o Portal do Motorista e preciso de auxílio.')
  assert.doesNotMatch(url.href, /motorista=|viagem=|latitude=|longitude=/i)
})

test('location age never presents missing or old information as current', () => {
  const now = new Date('2026-08-04T15:00:00Z').getTime()
  assert.equal(locationAgeLabel(null, now), 'Horário indisponível')
  assert.equal(locationAgeLabel('2026-08-04T14:59:40Z', now), 'Atualizada agora')
  assert.equal(locationAgeLabel('2026-08-04T13:00:00Z', now), 'Atualizada há 2 horas')
})

test('portal preserves the operational areas introduced in stage 1', () => {
  assert.match(app, /Próximos alertas/)
  assert.match(sharing, /Compartilhamento pelo celular/)
  assert.match(app, /WhatsApp Central/)
  assert.match(sharing, /A página deverá permanecer aberta/)
  assert.match(styles, /@media\(max-width:600px\)/)
})
