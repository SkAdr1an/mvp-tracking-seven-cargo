import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const map = readFileSync(new URL('./DriverMap.tsx', import.meta.url), 'utf8')
const css = readFileSync(new URL('../operational-map.css', import.meta.url), 'utf8')
const overview = readFileSync(new URL('../pages/Overview.tsx', import.meta.url), 'utf8')

test('operational map keeps compact CDs with active-route hierarchy and accessible details', () => {
  assert.match(map, /siteRouteRole\(site,activeRoute\)/)
  assert.match(map, /site-marker--\$\{role\}/)
  assert.match(map, /<Tooltip direction="top">\{site\.name\}/)
  assert.doesNotMatch(map, /mapIcon\('site','CD'\)/)
  assert.match(css, /\.site-marker--origin/)
  assert.match(css, /\.site-marker--destination/)
  assert.match(css, /\.site-marker--neutral/)
  assert.match(css, /\.site-marker:after/)
  assert.match(map, /role==='neutral'\?0:role==='intermediate'\?50:200/)
})

test('vehicle keeps the original operational marker', () => {
  assert.match(map, /<CircleMarker pane="vehicle-markers" key=\{driver\.id\}/)
  assert.match(map, /radius=\{selected\?\.id===driver\.id\?11:8\}/)
  assert.match(map, /pathOptions=\{\{color:'#fff',weight:2,fillColor:color,fillOpacity:1\}\}/)
  assert.doesNotMatch(map, /truckIcon|zIndexOffset=\{1200\}/)
})

test('normal drivers use the green operational status color', () => {
  assert.match(map, /classification==='NORMAL'\?'#38d996'/)
})

test('route, controls and legend expose the simplified visual hierarchy', () => {
  assert.match(map, /dashArray:'5 9'/)
  assert.match(map, /className="operational-progress"/)
  assert.match(map, /<b>Status<\/b>/)
  assert.match(map, /<b>Trajeto<\/b>/)
  assert.match(map, /<b>Operação<\/b>/)
  assert.doesNotMatch(css, /\.operational-map \.map-filters button\{[^}]*height:/)
})

test('dark treatment affects only the base tiles and preserves operational overlays', () => {
  assert.match(css, /\.operational-map \.leaflet-tile-pane\{filter:/)
  assert.match(css, /\.premium-overview \.operational-map \.map,.operational-map \.map\{filter:none/)
  assert.doesNotMatch(css, /\.operational-map \.leaflet-overlay-pane\{filter:/)
  assert.doesNotMatch(css, /\.operational-map \.leaflet-marker-pane\{filter:/)
})

test('map filters keep their dimensions but no longer flash white', () => {
  assert.match(css, /\.premium-overview \.operational-map \.map-filters button\{transition:none/)
  assert.match(css, /button\.active:hover\{border-color:#d4aa2d;background:#e2b32f/)
  assert.doesNotMatch(css, /\.operational-map \.map-filters button\{[^}]*height:/)
  assert.doesNotMatch(css, /\.operational-map \.map-filters button\{[^}]*padding:/)
})

test('CD button opens operation checkboxes without changing site data', () => {
  assert.match(map, /aria-expanded=\{sitesMenuOpen\}/)
  assert.match(map, /Filtrar CDs por operação/)
  assert.match(map, />Todas<\/span>/)
  assert.match(map, /Outras transportadoras \/ operações/)
  assert.match(map, /visibleSites\.map/)
  assert.match(map, /siteRadii&&visibleSites\.flatMap/)
  assert.match(css, /\.site-filter-popover/)
})

test('weather uses condition-specific symbols without changing risk data', () => {
  assert.match(map, /weatherVisual\(risk\)/)
  assert.match(map, /icon=\{weatherIcon\(visual\.kind,visual\.severity\)\}/)
  assert.match(map, /<Tooltip direction="top">\{visual\.label\}<\/Tooltip>/)
  assert.match(map, /risk\.position\.latitude,risk\.position\.longitude/)
  assert.match(map, /risk\.description/)
  assert.match(map, /'heavy-rain'/)
  assert.match(map, /storm:/)
  assert.match(css, /\.weather-marker--heavy-rain/)
  assert.match(css, /\.weather-marker--storm/)
  assert.match(css, /\.weather-marker__detail/)
})

test('vehicles keep visual priority and nearby context markers are displaced', () => {
  assert.match(map, /Pane name="context-connectors" style=\{\{zIndex:445\}\}/)
  assert.match(map, /Pane name="context-markers" style=\{\{zIndex:520\}\}/)
  assert.match(map, /Pane name="vehicle-markers" style=\{\{zIndex:680\}\}/)
  assert.match(map, /CircleMarker pane="vehicle-markers"/)
  assert.match(map, /distance<44/)
  assert.match(map, /displacement=46/)
  assert.match(map, /Polyline pane="context-connectors"/)
  assert.match(map, /Marker pane="context-markers"/)
  assert.match(map, /visibleDrivers=.*sort/)
})

test('TV cockpit uses idle space above the minimap for nonzero signals only', () => {
  assert.match(overview, /cockpitSignals=metrics\.filter/)
  assert.match(overview, /key!=='trips'&&key!=='normal'&&value>0/)
  assert.match(overview, /map-cockpit__signals/)
  assert.match(css, /\.map-cockpit__signals\{[^}]*bottom:347px/)
  assert.match(css, /\.map-cockpit__signals\{[^}]*grid-template-columns:1fr/)
  assert.match(css, /\.map-cockpit__signals\{[^}]*width:240px/)
  assert.match(css, /\.map-cockpit__signal\{[^}]*min-height:42px/)
  assert.match(overview, /<article key=\{key\} className=\{`map-cockpit__signal/)
  assert.doesNotMatch(overview, /map-cockpit__signal[^\n]*onClick/)
  assert.match(css, /@media\(max-width:900px\)\{\.map-cockpit__signals\{display:none\}\}/)
})
