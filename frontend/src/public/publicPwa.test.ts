import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const main = readFileSync(new URL('../main.tsx', import.meta.url), 'utf8')
const app = readFileSync(new URL('./PublicTripApp.tsx', import.meta.url), 'utf8')
const hook = readFileSync(new URL('./hooks/usePublicTrip.ts', import.meta.url), 'utf8')
const publicApi = readFileSync(new URL('./api.ts', import.meta.url), 'utf8')
const map = readFileSync(new URL('./PublicTripMap.tsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('./public-trip.css', import.meta.url), 'utf8')
const worker = readFileSync(new URL('../../public/viagem/sw.js', import.meta.url), 'utf8')
const manifest = JSON.parse(readFileSync(new URL('../../public/viagem/manifest.webmanifest', import.meta.url), 'utf8'))

test('PWA bootstrap is restricted to the public trip route', () => {
  assert.match(main, /\/viagem\//)
  assert.match(main, /preparePublicTripPwa/)
  const administrativeBranch = main.slice(main.lastIndexOf('} else {'))
  assert.match(administrativeBranch, /<App \/>/)
  assert.doesNotMatch(administrativeBranch, /preparePublicTripPwa|registerServiceWorker/)
})

test('offline state and last synchronization are explicit to the driver', () => {
  assert.match(app, /Você está sem internet\. Mostrando dados da última atualização\./)
  assert.match(app, /Última sincronização/)
  assert.match(hook, /addEventListener\('online'/)
  assert.match(hook, /addEventListener\('offline'/)
})

test('service worker caches static shell but never API responses or token routes', () => {
  assert.match(worker, /STATIC_CACHE/)
  assert.match(worker, /request\.mode === 'navigate'/)
  assert.match(worker, /url\.pathname\.startsWith\('\/api\/'\)/)
  assert.match(worker, /!url\.startsWith\('\/viagem\/'\)/)
  assert.doesNotMatch(worker, /cache\.put\(request[\s\S]*\/api\//)
  assert.match(worker, /seven-public-trip-static-v3/)
  assert.match(main + readFileSync(new URL('./registerServiceWorker.ts', import.meta.url), 'utf8'), /updateViaCache: 'none'/)
})

test('manifest uses Seven identity, standalone display, and identified placeholder icons', () => {
  assert.equal(manifest.name, 'Seven Cargo')
  assert.equal(manifest.short_name, 'Seven')
  assert.equal(manifest.display, 'standalone')
  assert.equal(manifest.theme_color, '#f3c623')
  assert.ok(manifest.icons.every((icon: { src: string }) => icon.src.includes('placeholder')))
})

test('public portal only calls its token-scoped endpoint', () => {
  assert.match(publicApi, /\/api\/public\/trips\/\$\{encodeURIComponent\(token\)\}/)
  assert.doesNotMatch(`${publicApi}${hook}`, /\/fleet|\/tracking|\/traffic|\/operations|\/routes/)
  assert.match(publicApi, /credentials: 'omit'/)
})

test('token changes discard stale responses and remount isolated map layers', () => {
  assert.match(hook, /activeToken\.current !== requestToken/)
  assert.match(hook, /requestSequence\.current !== sequence/)
  assert.match(hook, /setRecord\(undefined\)/)
  assert.match(app, /<PublicTripMap key=\{token\} trip=\{trip\}/)
  assert.match(map, /position && <Marker/)
})

test('route and markers are visually differentiated without coordinate fallbacks', () => {
  assert.match(map, /splitRouteAtPosition/)
  assert.equal((map.match(/<Polyline/g) || []).length, 3)
  assert.match(map, /color: '#35b871', weight: 6, opacity: 1/)
  assert.match(map, /color: '#f3c623'[\s\S]*dashArray: '4 10'/)
  assert.doesNotMatch(map, /latitude: -14\.2|longitude: -51\.9/)
  assert.match(map, /public-map-marker--origin/)
  assert.match(map, /public-map-marker--destination/)
  assert.match(map, /public-map-marker--vehicle/)
  assert.match(map, /Localização ainda não disponível/)
})

test('public route card shows linked CDs, locality and travel direction responsively', () => {
  assert.match(app, /CD de origem/)
  assert.match(app, /CD de destino/)
  assert.match(app, /sentido da viagem/)
  assert.match(app, /place\.city && place\.state/)
  assert.match(styles, /\.public-route-card\{[^}]*grid-template-columns:minmax\(0,1fr\) 150px minmax\(0,1fr\)/)
  assert.match(styles, /@media\(max-width:600px\)[\s\S]*\.public-route-card\{grid-template-columns:1fr/)
  assert.match(styles, /\.public-route-line svg\{transform:rotate\(90deg\)/)
})

test('public map labels endpoints, vehicle, alerts and operational controls', () => {
  assert.match(map, /<strong>Origem<\/strong>/)
  assert.match(map, /<strong>Destino<\/strong>/)
  assert.match(map, /distances\.travelledKm/)
  assert.match(map, /distances\.remainingKm/)
  assert.match(map, /Posição atual do veículo/)
  assert.match(map, /Centralizar no veículo/)
  assert.match(map, /Ajustar à rota completa/)
  assert.match(map, /MapLegend/)
  assert.match(map, /AlertMarker/)
})
