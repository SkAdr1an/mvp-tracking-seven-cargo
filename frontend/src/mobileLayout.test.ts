import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const responsive = readFileSync(new URL('./mobile-responsive.css', import.meta.url), 'utf8')
const shell = readFileSync(new URL('./mobile-shell.css', import.meta.url), 'utf8')
const map = readFileSync(new URL('./mobile-map.css', import.meta.url), 'utf8')
const operationalPanel = readFileSync(new URL('./components/OperationalTripPanel.tsx', import.meta.url), 'utf8')
const drivers = readFileSync(new URL('./pages/Drivers.tsx', import.meta.url), 'utf8')
const overview = readFileSync(new URL('./pages/Overview.tsx', import.meta.url), 'utf8')
const sidebar = readFileSync(new URL('./components/Sidebar.tsx', import.meta.url), 'utf8')
const app = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8')
const appBoundary = readFileSync(new URL('./components/ContentErrorBoundary.tsx', import.meta.url), 'utf8')
const driverMap = readFileSync(new URL('./components/DriverMap.tsx', import.meta.url), 'utf8')

test('mobile layout covers the supported handset and tablet widths', () => {
  assert.match(responsive, /max-width:\s*900px/)
  assert.match(responsive, /max-width:\s*600px/)
  assert.match(responsive, /max-width:\s*380px/)
  assert.match(responsive, /orientation:\s*landscape/)
})

test('mobile layout avoids horizontal metric scrolling and provides touch targets', () => {
  assert.match(responsive, /\.overview-metrics[\s\S]*grid-template-columns/)
  assert.match(responsive, /min-height:\s*44px/)
  assert.match(responsive, /overflow-x:\s*hidden/)
})

test('mobile layout supports safe areas and dynamic viewport height', () => {
  assert.match(`${responsive}${shell}${map}`, /env\(safe-area-inset-/)
  assert.match(`${responsive}${shell}${map}`, /100dvh/)
})

test('mobile navigation and map use compact accessible controls', () => {
  assert.match(shell, /max-width:\s*900px/)
  assert.match(map, /map-filters-toggle/)
  assert.match(map, /min-height:\s*44px/)
})

test('operational actions use the controlled confirmation dialog', () => {
  assert.doesNotMatch(operationalPanel, /window\.prompt/)
  assert.match(operationalPanel, /OperationalActionDialog/)
  assert.match(operationalPanel, /operation-feedback/)
})

test('driver mobile cards expose the required operational fields', () => {
  for (const label of ['Rota', 'Sentido', 'Progresso', 'Atualização']) {
    assert.match(drivers, new RegExp(label))
  }
})

test('drivers tab keeps operational controls and public-link management available', () => {
  assert.match(drivers, /import \{ OperationalTripPanel \}/)
  assert.match(drivers, /selected\.operational && <OperationalTripPanel initial=\{selected\.operational\}\/>/)
})

test('sidebar changes central content without links or a separate browser page', () => {
  assert.match(sidebar, /<button[\s\S]*type="button"/)
  assert.match(sidebar, /type="button"[\s\S]*onChange\(itemPage\)/)
  assert.match(sidebar, /onChange\(itemPage\)/)
  assert.doesNotMatch(sidebar, /<a(?:\s|>)|href=|target=|window\.open|location\.href/)
  assert.match(app, /const \[page, setPage\] = useState<Page>\('overview'\)/)
  assert.match(app, /<Sidebar page=\{page\} onChange=\{setPage\}/)
  assert.match(styles, /\.sidebar \.nav__item[^}]*text-decoration:none/)
})

test('drivers list preserves operational data and map visibility controls', () => {
  for (const value of ['location_description', 'prediction?.eta_at', 'formatAgo(driver.last_update)', 'onPin(driver.id)', 'onHide(driver.id)', '<Check', '<X']) {
    assert.match(drivers, new RegExp(value.replace(/[?.()]/g, '\\$&')))
  }
})

test('central content failure preserves navigation and offers recovery', () => {
  assert.match(app, /<Header[\s\S]*<ContentErrorBoundary/)
  assert.match(appBoundary, /Tentar novamente/)
  assert.match(appBoundary, /Voltar à visão geral/)
  assert.match(appBoundary, /sanitizedErrorContext/)
})

test('map renders neutral distribution centers and independently controlled radii', () => {
  assert.match(driverMap, /OperationalSite/)
  assert.match(driverMap, /\['sites','CDs'\]/)
  assert.match(driverMap, /\['siteRadii','Raios dos CDs'\]/)
  assert.match(driverMap, /site-radius--entry/)
  assert.match(driverMap, /site-radius--exit/)
  assert.match(driverMap, /site-radius--approach/)
})

test('main map presents physical points only as reusable CDs',()=>{
  assert.match(driverMap,/icon=\{mapIcon\('site','CD'\)\}/)
  assert.match(driverMap,/CDs · entrada 500 m/)
  assert.doesNotMatch(driverMap,/mapIcon\('origin','O'\)|mapIcon\('destination','D'\)/)
  assert.doesNotMatch(driverMap,/<strong>Origem<\/strong>|<strong>Destino<\/strong>/)
})

test('overview identifies trips without a safe route association', () => {
  const source = readFileSync(new URL('./pages/Overview.tsx', import.meta.url), 'utf8')
  assert.match(source, /Geometria pendente/)
  assert.match(source, /Rota ambígua/)
  assert.match(source, /Rota não identificada/)
})
