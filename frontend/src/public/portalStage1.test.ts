import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { buildCentralWhatsAppMessage, buildCentralWhatsAppUrl, locationAgeLabel } from './portalUtils.ts'
import type { PublicTrip } from './types.ts'

const app = readFileSync(new URL('./PublicTripApp.tsx', import.meta.url), 'utf8')
const sharing = readFileSync(new URL('./MobileLocationSharing.tsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('./public-trip.css', import.meta.url), 'utf8')

const completeTrip = {
  driver_name: 'João da Silva', trip_reference: 'CEVA-4587',
  route: { name: 'Rota', origin: { name: 'Betim', city: 'Betim', state: 'MG' }, destination: { name: 'Jaboatão', city: 'Jaboatão', state: 'PE' }, geometry: [], important_points: [] },
  vehicle: { plate: 'ABC1D23' }, public_status: 'Em viagem', last_updated_at: '', stale: false, finished: false,
  location_sources: { situation: 'UNAVAILABLE' }, mobile_location_enabled: false, portal_alerts_enabled: false,
  operational_instructions: [], central_contact: { name: 'Central' }, notices: [],
} as PublicTrip

test('WhatsApp Central builds the complete message only from backend trip data', () => {
  const url = new URL(buildCentralWhatsAppUrl(completeTrip))
  assert.equal(`${url.origin}${url.pathname}`, 'https://wa.me/553584027743')
  assert.equal(url.searchParams.get('text'), 'Olá, Central Seven Cargo! Sou João da Silva, viagem CEVA-4587, na rota Betim/MG → Jaboatão/PE, veículo ABC1D23. Preciso de atendimento.')
  assert.doesNotMatch(url.searchParams.get('text') || '', /token|latitude|longitude/i)
})

test('WhatsApp message omits incomplete fields and never prints empty placeholders', () => {
  const incomplete = { ...completeTrip, driver_name: 'Motorista não informado', trip_reference: null, vehicle: { plate: '' }, route: { ...completeTrip.route, destination: { name: '', city: null, state: null } } }
  const message = buildCentralWhatsAppMessage(incomplete)
  assert.equal(message, 'Olá, Central Seven Cargo! Preciso de atendimento.')
  assert.doesNotMatch(message, /undefined|null|Motorista não informado|→/)
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
  assert.match(sharing, /Compartilhar localização/)
  assert.doesNotMatch(sharing, /A página deverá permanecer aberta/)
  assert.match(styles, /@media\(max-width:600px\)/)
})

test('driver name remains only in the main portal identification', () => {
  assert.equal((app.match(/trip\.driver_name/g) || []).length, 1)
  assert.doesNotMatch(app, /label="Motorista"/)
})
