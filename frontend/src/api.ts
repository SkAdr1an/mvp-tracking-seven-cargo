import type { AngelLiraAdminResponse, AngelLiraStationsResponse, FleetSnapshot, IntegrationStatus, OperationalSitesResponse, OperationalTrip, PanelSession, PublicLinkCreated, PublicLinkStatus, RoutePaths, RoutePreview, TrafegusResult, TrafficSnapshot } from './types'

const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
// Keep development panel authentication same-origin so the Strict HttpOnly
// cookie works through localhost, 127.0.0.1 and LAN addresses alike.
const PANEL_API_URL = import.meta.env.DEV ? '' : API_URL
const TRACKING_TOKEN = import.meta.env.VITE_TRACKING_TOKEN || ''
export const ADMIN_SESSION_EXPIRED_EVENT = 'seven:admin-session-expired'
let panelSessionGeneration = 0

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  headers.set('Content-Type', 'application/json')
  if (TRACKING_TOKEN && (path.startsWith('/tracking') || path.startsWith('/traffic') || path.startsWith('/operations') || path.startsWith('/routes') || path.startsWith('/deviations') || path.startsWith('/angellira'))) {
    headers.set('Authorization', `Bearer ${TRACKING_TOKEN}`)
  }

  const response = await fetch(`${API_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const message = typeof detail === 'string'
      ? detail
      : detail?.upstream_message || `Falha na solicitação (${response.status})`
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

async function panelRequest<T>(path: string, options?: RequestInit, allowNotFound = false): Promise<T | null> {
  const requestGeneration = panelSessionGeneration
  const headers = new Headers(options?.headers)
  headers.set('Content-Type', 'application/json')
  const response = await fetch(`${PANEL_API_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  })
  if (allowNotFound && response.status === 404) return null
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const isLoginAttempt = path === '/api/auth/session' && options?.method === 'POST'
    if (response.status === 401 && !isLoginAttempt && requestGeneration === panelSessionGeneration) {
      window.dispatchEvent(new CustomEvent(ADMIN_SESSION_EXPIRED_EVENT, {
        detail: { returnPath: `${window.location.pathname}${window.location.search}` },
      }))
      throw new Error('Sua sessão expirou. Entre novamente.')
    }
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : `Falha na solicitação (${response.status})`)
  }
  if (response.status === 204) return null
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  integrations: () => request<IntegrationStatus>('/integrations/status'),
  activeFleet: () => request<FleetSnapshot>('/fleet/active'),
  routePreview: (input: { origin: string; destination: string; departure_at: string; operational_speed_min_kmh: number; operational_speed_max_kmh: number; waypoints: string[]; route_profile?: string }) =>
    request<RoutePreview>('/routes/preview', { method: 'POST', body: JSON.stringify(input) }),
  consultPlate: (plate: string) =>
    request<TrafegusResult>('/trafegus/vehicles/consult', {
      method: 'POST',
      body: JSON.stringify({ plate }),
    }),
  operationalTrip: (tripKey: string) =>
    request<OperationalTrip>(`/operations/trips/${encodeURIComponent(tripKey)}`),
  operationalAction: (tripKey: string, input: { action: 'finalize' | 'reopen' | 'undo_detection' | 'correct_times'; justification: string; operator?: string; corrections?: Record<string, string | null> }) =>
    panelRequest<OperationalTrip>(`/operations/trips/${encodeURIComponent(tripKey)}/actions`, {
      method: 'POST', body: JSON.stringify(input),
    }) as Promise<OperationalTrip>,
  returnDecision: (candidateId: number, input: { decision: 'YES' | 'NO' | 'LATER'; operator?: string; justification?: string }) =>
    request<OperationalTrip>(`/operations/return-candidates/${candidateId}/decision`, {
      method: 'POST', body: JSON.stringify(input),
    }),
  trafficIncidents: () => request<TrafficSnapshot>('/traffic/incidents'),
  routePaths: () => request<RoutePaths>('/routes/paths'),
  operationalSites: () => request<OperationalSitesResponse>('/operational-sites'),
  createManualIncident: (input: Record<string, unknown>) => request('/traffic/manual', { method: 'POST', body: JSON.stringify(input) }),
  angelLiraStations: () => request<AngelLiraStationsResponse>('/angellira/stations?status=validated'),
  angelLiraAdmin: () => request<AngelLiraAdminResponse>('/angellira/admin'),
  panelSession: () => panelRequest<PanelSession>('/api/auth/session') as Promise<PanelSession>,
  panelMe: () => panelRequest<PanelSession>('/api/auth/me') as Promise<PanelSession>,
  panelLogin: async (input: { username: string; password: string }) => {
    const session = await panelRequest<PanelSession>('/api/auth/session', { method: 'POST', body: JSON.stringify(input) }) as PanelSession
    panelSessionGeneration += 1
    return session
  },
  panelLogout: async () => {
    const result = await panelRequest('/api/auth/session', { method: 'DELETE' })
    panelSessionGeneration += 1
    return result
  },
  publicLinkStatus: (tripId: string) =>
    panelRequest<PublicLinkStatus>(`/api/trips/${encodeURIComponent(tripId)}/public-link`, undefined, true),
  createPublicLink: (tripId: string) =>
    panelRequest<PublicLinkCreated>(`/api/trips/${encodeURIComponent(tripId)}/public-link`, {
      method: 'POST', body: JSON.stringify({}),
    }) as Promise<PublicLinkCreated>,
  revokePublicLink: (tripId: string) =>
    panelRequest(`/api/trips/${encodeURIComponent(tripId)}/public-link`, { method: 'DELETE' }),
}

export function trackingSocketUrl(): string {
  const base = (import.meta.env.VITE_WS_URL || API_URL.replace(/^http/, 'ws')).replace(/\/$/, '')
  const token = import.meta.env.VITE_TRACKING_TOKEN || ''
  return `${base}/tracking/ws/manager${token ? `?token=${encodeURIComponent(token)}` : ''}`
}
