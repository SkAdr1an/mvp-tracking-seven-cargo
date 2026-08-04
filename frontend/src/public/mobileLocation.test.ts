import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const sharing = readFileSync(new URL('./MobileLocationSharing.tsx', import.meta.url), 'utf8')
const hook = readFileSync(new URL('./hooks/useMobileLocation.ts', import.meta.url), 'utf8')
const api = readFileSync(new URL('./api.ts', import.meta.url), 'utf8')

test('GPS permission is requested only after explicit consent action', () => {
  assert.match(sharing, /Entendi e quero compartilhar/)
  assert.match(sharing, /onClick=\{sharing\.start\}/)
  assert.match(hook, /navigator\.geolocation\.watchPosition/)
  assert.doesNotMatch(hook, /useEffect\([\s\S]{0,200}watchPosition/)
})

test('consent explains collection, interruption and browser limitations', () => {
  assert.match(sharing, /latitude, longitude, precisão e horário/)
  assert.match(sharing, /pode ser interrompido/)
  assert.match(sharing, /página deve permanecer aberta/)
  assert.match(sharing, /tela estiver bloqueada ou minimizada/)
  assert.match(sharing, /link deixa de aceitar posições quando expira/)
})

test('mobile positions remain token scoped and are throttled client side', () => {
  assert.match(api, /public\/trips\/\$\{encodeURIComponent\(token\)\}\/positions/)
  assert.match(api, /accuracy_m: position\.coords\.accuracy/)
  assert.match(api, /credentials: 'omit'/)
  assert.match(hook, /15_000/)
  assert.match(hook, /clearWatch/)
})
