import assert from 'node:assert/strict'
import test from 'node:test'
import { createdPublicLink, managedPublicUrl, mergePublicLinkStatus, publicLinkState, whatsappShareUrl } from './publicLinkUtils.ts'

const token = 'A'.repeat(43)

test('public URL uses configured frontend domain and preserves only the generated token', () => {
  const result = managedPublicUrl(
    `https://backend.example/viagem/${token}`,
    'https://portal.sevencargo.com.br',
  )
  assert.equal(result, `https://portal.sevencargo.com.br/viagem/${token}`)
  assert.doesNotMatch(result, /localhost|backend\.example/)
})

test('configured URL may include viagem without duplicating the route', () => {
  const result = managedPublicUrl(
    `https://backend.example/viagem/${token}`,
    'http://localhost:5173/viagem/',
  )
  assert.equal(result, `http://localhost:5173/viagem/${token}`)
})

test('WhatsApp message is correctly encoded with driver and link', () => {
  const link = `https://portal.sevencargo.com.br/viagem/${token}`
  const result = whatsappShareUrl('João da Silva', link)
  assert.match(result, /^https:\/\/wa\.me\/\?text=/)
  const message = decodeURIComponent(result.split('text=')[1])
  assert.match(message, /Olá, João da Silva\./)
  assert.match(message, new RegExp(link))
  assert.match(message, /rota, o status atual e a previsão de chegada/)
  assert.match(message, /Central Seven Cargo/)
})

test('link status distinguishes active, expired and revoked', () => {
  const base = {
    id: 'id',
    created_at: '2026-01-01T00:00:00Z',
    access_count: 0,
  }
  assert.equal(publicLinkState({ ...base, active: true }), 'active')
  assert.equal(publicLinkState({ ...base, active: false, revoked_at: '2026-01-02T00:00:00Z' }), 'revoked')
  assert.equal(publicLinkState({ ...base, active: false, expires_at: '2020-01-01T00:00:00Z' }), 'expired')
})

const created = {
  id: '42',
  url: `https://portal.sevencargo.com.br/viagem/${token}`,
  created_at: '2026-07-27T12:00:00Z',
  expires_at: '2027-07-27T12:00:00Z',
  active: true,
}
const sameStatus = {
  id: '42',
  created_at: created.created_at,
  expires_at: created.expires_at,
  active: true,
  access_count: 0,
}

test('POST 201 followed by GET 200 with the same id preserves the authoritative URL', () => {
  const postState = createdPublicLink(created, created.url)
  const afterGet = mergePublicLinkStatus(postState, sameStatus)
  assert.equal(afterGet.url, created.url)
  assert.equal(afterGet.id, '42')
})

test('GET without url does not erase the URL and string/number ids are normalized', () => {
  const postState = createdPublicLink(created, created.url)
  const afterGet = mergePublicLinkStatus(postState, { ...sameStatus, id: 42 as unknown as string })
  assert.equal(afterGet.url, created.url)
  assert.equal(afterGet.id, '42')
})

test('GET with a different id clears the URL', () => {
  const postState = createdPublicLink(created, created.url)
  assert.equal(mergePublicLinkStatus(postState, { ...sameStatus, id: '43' }).url, null)
})

test('GET active=false preserves identity and exposes the inactive state', () => {
  const postState = createdPublicLink(created, created.url)
  const afterGet = mergePublicLinkStatus(postState, { ...sameStatus, active: false })
  assert.equal(afterGet.url, created.url)
  assert.equal(afterGet.active, false)
})
