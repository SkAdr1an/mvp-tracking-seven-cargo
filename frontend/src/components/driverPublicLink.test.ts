import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(new URL('./DriverPublicLink.tsx', import.meta.url), 'utf8')
const operationalPanel = readFileSync(new URL('./OperationalTripPanel.tsx', import.meta.url), 'utf8')
const api = readFileSync(new URL('../api.ts', import.meta.url), 'utf8')
const viteConfig = readFileSync(new URL('../../vite.config.ts', import.meta.url), 'utf8')

test('trip detail includes the isolated driver-link administration section', () => {
  assert.match(operationalPanel, /<DriverPublicLink trip=\{trip\}/)
  assert.match(component, /Link do motorista/)
})

test('administration supports all requested link actions', () => {
  for (const action of ['Gerar link', 'Copiar link', 'Abrir em nova aba', 'Compartilhar pelo WhatsApp', 'Revogar', 'Gerar novo link']) {
    assert.match(component, new RegExp(action))
  }
  for (const state of ['Ativo', 'Expirado', 'Revogado']) {
    assert.match(component, new RegExp(state))
  }
  assert.match(component, /Criado em/)
  assert.match(component, /Último acesso/)
})

test('new generation is authoritative, cancels stale GET and binds URL to backend link id', () => {
  assert.match(component, /cancelQueries\(\{ queryKey: \['public-link', tripKey\] \}\)/)
  assert.match(component, /createdPublicLink\(created, url\)/)
  assert.match(component, /queryClient\.setQueryData<PublicLinkStatus>/)
  assert.match(component, /context\.tripKey !== tripKeyRef\.current/)
  assert.match(component, /String\(previous\.id\) !== String\(current\.id\)/)
})

test('double click is guarded and trip change clears the unified state', () => {
  assert.match(component, /creationInFlightRef\.current \|\| create\.isPending/)
  assert.match(component, /creationInFlightRef\.current = true/)
  assert.match(component, /storeLink\(null\)[\s\S]*\}, \[trip\.trip_key\]\)/)
})

test('link administration uses cookie session and never embeds the internal API key', () => {
  assert.match(api, /credentials:\s*'include'/)
  assert.match(component, /panelLogin/)
  assert.doesNotMatch(`${component}${api}`, /PUBLIC_TRIP_INTERNAL_API_KEY/)
  assert.match(api, /Sua sessão expirou\. Entre novamente\./)
  const panelRequest = api.slice(api.indexOf('async function panelRequest'), api.indexOf('export const api'))
  assert.doesNotMatch(panelRequest, /headers\.set\('Authorization'/)
})

test('administrative 401 clears the visual session and offers reauthentication', () => {
  assert.match(api, /ADMIN_SESSION_EXPIRED_EVENT/)
  assert.match(api, /window\.dispatchEvent\(new CustomEvent/)
  assert.match(component, /queryClient\.setQueryData\(\['panel-session'\], null\)/)
  assert.match(component, /queryClient\.removeQueries\(\{ queryKey: \['public-link'\] \}\)/)
  assert.match(component, /Sua sessão expirou\./)
  assert.match(component, /Entrar novamente/)
  assert.match(component, /return api\.panelMe\(\)/)
  assert.match(component, /invalidateQueries\(\{ queryKey: \['public-link', trip\.trip_key\] \}\)/)
})

test('development panel requests are same-origin and preserve the /api cookie path', () => {
  assert.match(api, /const PANEL_API_URL = import\.meta\.env\.DEV \? '' : API_URL/)
  assert.match(api, /fetch\(`\$\{PANEL_API_URL\}\$\{path\}`/)
  assert.match(viteConfig, /'\/api':[\s\S]*target: 'http:\/\/localhost:8000'/)
  assert.doesNotMatch(viteConfig, /rewrite:/)
})

test('successful reauthentication supersedes stale 401 responses', () => {
  assert.match(api, /let panelSessionGeneration = 0/)
  assert.match(api, /requestGeneration === panelSessionGeneration/)
  assert.match(api, /panelSessionGeneration \+= 1/)
  assert.match(component, /cancelQueries\(\{ queryKey: \['public-link'\] \}\)/)
  assert.match(component, /await api\.panelLogin\(credentials\)[\s\S]*return api\.panelMe\(\)/)
})
