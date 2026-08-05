import type { PortalAlertsResponse, PublicCoordinate, PublicTrip } from './types'

export const VISUAL_DEMO_TOKEN = 'visual-demo-seven-cargo-portal-motorista-2026'

const route: PublicCoordinate[] = [
  [-19.9676,-44.2014],[-19.8118,-43.1735],[-19.2249,-42.4823],[-18.8511,-41.9494],
  [-18.2427,-41.7350],[-17.8578,-41.5053],[-16.8692,-41.2473],[-15.6401,-40.7584],
  [-14.8619,-40.8446],[-13.8570,-40.0831],[-12.9714,-39.2569],[-12.2664,-38.9663],
  [-12.1356,-38.4192],[-11.3708,-37.6611],[-10.9091,-37.0677],[-10.2832,-36.5868],
  [-9.6658,-35.7353],[-8.8841,-35.1512],[-8.2058,-35.5679],[-8.1120,-35.0147],
].map(([latitude, longitude]) => ({ latitude, longitude }))

export function isVisualDemo(token: string): boolean { return import.meta.env.DEV && token === VISUAL_DEMO_TOKEN }

export function visualDemoTrip(now = new Date()): PublicTrip {
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
    latest_position: { ...route[5], recorded_at: recordedAt, speed_kmh: 55, source: 'Posição fictícia de demonstração' },
    location_sources: { trafegus: { ...route[5], recorded_at: recordedAt, speed_kmh: 55, source: 'Posição fictícia de demonstração', age_seconds: 0, status: 'CURRENT' }, mobile: null, difference_km: null, situation: 'TRAFEGUS_PRIMARY' },
    mobile_location_enabled: false, portal_alerts_enabled: true, operational_instructions: [],
    central_contact: { name: 'Central Seven Cargo' }, notices: [],
  }
}

export function visualDemoAlerts(now = new Date()): PortalAlertsResponse {
  const updated_at = now.toISOString()
  const base = { updated_at, presentation: 'NEW' as const, distance_band: 'FIRST' as const, delay_minutes: null }
  return { enabled: true, generated_at: updated_at, integrations: { traffic: 'OPERATIONAL', weather: 'CONNECTED' }, alerts: [
    { ...base, id: 'demo-traffic', type: 'TRANSITO_LENTO', severity: 'ATENCAO', distance_km: 113, reference: 'BR-116 — trecho fictício próximo a Itaobim/MG', source: 'Dados fictícios de demonstração', guidance: 'Reduza a velocidade e mantenha distância segura.', description: 'Trânsito lento fictício. Dados fictícios para demonstração.', latitude: route[6].latitude, longitude: route[6].longitude },
    { ...base, id: 'demo-blockage', type: 'ACIDENTE_BLOQUEIO', severity: 'CRITICO', distance_km: 346, reference: 'BR-116 — trecho fictício próximo a Vitória da Conquista/BA', source: 'Dados fictícios de demonstração', guidance: 'Atenção à sinalização e ao bloqueio parcial.', description: 'Bloqueio parcial fictício. Dados fictícios para demonstração.', latitude: route[8].latitude, longitude: route[8].longitude },
    { ...base, id: 'demo-rain', type: 'CHUVA_FORTE', severity: 'CRITICO', distance_km: 702, reference: 'BR-116 — trecho fictício próximo a Feira de Santana/BA', source: 'Dados fictícios de demonstração', guidance: 'Possibilidade de pista molhada e redução de visibilidade.', description: 'Chuva forte fictícia. Dados fictícios para demonstração.', latitude: route[11].latitude, longitude: route[11].longitude },
    { ...base, id: 'demo-normal', type: 'CLIMA_NORMAL', severity: 'INFORMATIVO', distance_km: 963, reference: 'BR-101 — trecho fictício próximo a Aracaju/SE', source: 'Dados fictícios de demonstração', guidance: 'Condição estável no trecho; mantenha a condução segura.', description: 'Condição climática normal fictícia. Dados fictícios para demonstração.', latitude: route[14].latitude, longitude: route[14].longitude },
  ] }
}
