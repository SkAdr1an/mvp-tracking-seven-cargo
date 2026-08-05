import type { PortalAlertsResponse, PublicCoordinate, PublicTrip } from './types'

export const VISUAL_DEMO_TOKEN = 'visual-demo-seven-cargo-portal-motorista-2026'
export const VISUAL_DEMO_POSITION_EVENT = 'seven:visual-demo-position'

const route: PublicCoordinate[] = [
  [-19.9676,-44.2014],[-19.8118,-43.1735],[-19.2249,-42.4823],[-18.8511,-41.9494],
  [-18.2427,-41.7350],[-17.8578,-41.5053],[-16.8692,-41.2473],[-15.6401,-40.7584],
  [-14.8619,-40.8446],[-13.8570,-40.0831],[-12.9714,-39.2569],[-12.2664,-38.9663],
  [-12.1356,-38.4192],[-11.3708,-37.6611],[-10.9091,-37.0677],[-10.2832,-36.5868],
  [-9.6658,-35.7353],[-8.8841,-35.1512],[-8.2058,-35.5679],[-8.1120,-35.0147],
].map(([latitude, longitude]) => ({ latitude, longitude }))

export function isVisualDemo(token: string): boolean { return import.meta.env.DEV && token === VISUAL_DEMO_TOKEN }

export function visualDemoPosition(): number {
  const value = Number(new URLSearchParams(window.location.search).get('posição') ?? 5)
  return Number.isInteger(value) ? Math.min(Math.max(value, 0), route.length - 1) : 5
}

export function setVisualDemoPosition(index: number) {
  const safe = Math.min(Math.max(Math.round(index), 0), route.length - 1)
  const url = new URL(window.location.href)
  url.searchParams.set('posição', String(safe))
  window.history.replaceState({}, '', url)
  window.dispatchEvent(new CustomEvent(VISUAL_DEMO_POSITION_EVENT, { detail: safe }))
}

export function visualDemoTrip(now = new Date(), positionIndex = visualDemoPosition()): PublicTrip {
  const recordedAt = now.toISOString()
  return {
    driver_name: 'Motorista Demonstração', trip_reference: 'DEMO-BR-2026', public_status: 'Em viagem',
    loaded_at: new Date(now.getTime() - 2 * 3600_000).toISOString(), last_updated_at: recordedAt,
    stale: false, finished: false, vehicle: { plate: 'DEM0A00' },
    route: {
      name: 'Betim/MG → Jaboatão dos Guararapes/PE',
      origin: { name: 'Betim', city: 'Betim', state: 'MG', coordinate: route[0] },
      destination: { name: 'Jaboatão dos Guararapes', city: 'Jaboatão dos Guararapes', state: 'PE', coordinate: route.at(-1)! },
      geometry: route, important_points: [],
    },
    latest_position: { ...route[positionIndex], recorded_at: recordedAt, speed_kmh: 55, source: 'Posição fictícia de demonstração' },
    location_sources: { trafegus: { ...route[positionIndex], recorded_at: recordedAt, speed_kmh: 55, source: 'Posição fictícia de demonstração', age_seconds: 0, status: 'CURRENT' }, mobile: null, difference_km: null, situation: 'TRAFEGUS_PRIMARY' },
    mobile_location_enabled: false, portal_alerts_enabled: true, operational_instructions: [],
    central_contact: { name: 'Central Seven Cargo' }, notices: [],
  }
}

export function visualDemoAlerts(now = new Date(), positionIndex = visualDemoPosition()): PortalAlertsResponse {
  const updated_at = now.toISOString()
  const base = { updated_at, presentation: 'NEW' as const, distance_band: 'FIRST' as const, delay_minutes: null }
  const definitions = [
    { index: 6, id: 'demo-traffic', type: 'TRANSITO_LENTO', severity: 'ATENCAO', reference: 'BR-116 — trecho fictício próximo a Itaobim/MG', guidance: 'Reduza a velocidade e mantenha distância segura.', description: 'Trânsito lento fictício.' },
    { index: 8, id: 'demo-blockage', type: 'ACIDENTE_BLOQUEIO', severity: 'CRITICO', reference: 'BR-116 — trecho fictício próximo a Vitória da Conquista/BA', guidance: 'Atenção à sinalização e ao bloqueio parcial.', description: 'Bloqueio parcial fictício.' },
    { index: 11, id: 'demo-rain', type: 'CHUVA_FORTE', severity: 'CRITICO', reference: 'BR-116 — trecho fictício próximo a Feira de Santana/BA', guidance: 'Possibilidade de pista molhada e redução de visibilidade.', description: 'Chuva forte fictícia.' },
    { index: 14, id: 'demo-normal', type: 'CLIMA_NORMAL', severity: 'INFORMATIVO', reference: 'BR-101 — trecho fictício próximo a Aracaju/SE', guidance: 'Condição estável no trecho; mantenha a condução segura.', description: 'Condição climática normal fictícia.' },
  ] as const
  const map_alerts = definitions.map((item) => {
    const signedDistance = routeDistance(positionIndex, item.index)
    return { ...base, id: item.id, type: item.type, severity: item.severity, distance_km: Math.round(Math.abs(signedDistance)), reference: item.reference, source: 'Dados fictícios de demonstração', guidance: item.guidance, description: `${item.description} Dado fictício de demonstração.`, latitude: route[item.index].latitude, longitude: route[item.index].longitude, signedDistance }
  })
  const alerts = map_alerts.filter((item) => item.signedDistance >= 0 && item.type !== 'CLIMA_NORMAL' && (item.signedDistance <= 150 || (item.signedDistance <= 250 && item.severity === 'CRITICO'))).map(stripSignedDistance)
  return { enabled: true, generated_at: updated_at, integrations: { traffic: 'OPERATIONAL', weather: 'CONNECTED' }, alerts, map_alerts: map_alerts.map(stripSignedDistance) }
}

function stripSignedDistance<T extends { signedDistance: number }>(item: T): Omit<T, 'signedDistance'> {
  const copy = { ...item }; delete (copy as Partial<T>).signedDistance; return copy
}

function routeDistance(from: number, to: number): number {
  const direction = to >= from ? 1 : -1
  let total = 0
  for (let index = from; index !== to; index += direction) total += haversine(route[index], route[index + direction])
  return total * direction
}

function haversine(a: PublicCoordinate, b: PublicCoordinate): number {
  const radius = 6371.0088; const radians = Math.PI / 180
  const lat1 = a.latitude * radians; const lat2 = b.latitude * radians
  const dLat = lat2 - lat1; const dLon = (b.longitude - a.longitude) * radians
  const value = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return radius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value))
}
