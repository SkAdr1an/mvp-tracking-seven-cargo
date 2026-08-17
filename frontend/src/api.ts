import type { AngelLiraAdminResponse, AngelLiraStationsResponse, AuditResponse, DriverHistorySummary, DriverHistoryTrip, DriverProfile, FleetSnapshot, IntegrationStatus, ManagedUser, OperationalObservation, OperationalSitesResponse, OperationalTrip, Paged, PanelSession, PendingEvaluation, PublicLinkCreated, PublicLinkStatus, RoutePaths, RoutePreview, TrafegusResult, TrafficSnapshot } from './types'

const API_URL = (import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/$/, '')
// Keep development panel authentication same-origin so the Strict HttpOnly
// cookie works through localhost, 127.0.0.1 and LAN addresses alike.
const PANEL_API_URL = import.meta.env.DEV ? '' : API_URL
export const ADMIN_SESSION_EXPIRED_EVENT = 'seven:admin-session-expired'
export const PANEL_FORBIDDEN_EVENT = 'seven:panel-forbidden'
let panelSessionGeneration = 0

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_URL}${path}`, { ...options, headers, credentials: 'include' })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const message = typeof detail === 'string'
      ? detail
      : detail?.upstream_message || `Falha na solicitação (${response.status})`
    if (response.status === 401) window.dispatchEvent(new CustomEvent(ADMIN_SESSION_EXPIRED_EVENT))
    if (response.status === 403) window.dispatchEvent(new CustomEvent(PANEL_FORBIDDEN_EVENT))
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
    if (response.status === 403) {
      window.dispatchEvent(new CustomEvent(PANEL_FORBIDDEN_EVENT))
      throw new Error('Você não possui permissão para realizar esta ação.')
    }
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : `Falha na solicitação (${response.status})`)
  }
  if (response.status === 204) return null
  return response.json() as Promise<T>
}

async function downloadPanelPdf(path: string): Promise<void> {
  const response = await fetch(`${PANEL_API_URL}${path}`, {
    method: 'POST', credentials: 'include', headers: { Accept: 'application/pdf' },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(ADMIN_SESSION_EXPIRED_EVENT, {
        detail: { returnPath: `${window.location.pathname}${window.location.search}` },
      }))
    }
    if (response.status === 403) {
      window.dispatchEvent(new CustomEvent(PANEL_FORBIDDEN_EVENT))
      throw new Error('Você não possui permissão para realizar esta ação.')
    }
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : 'Não foi possível gerar o relatório.')
  }
  if (!response.headers.get('content-type')?.toLowerCase().startsWith('application/pdf')) {
    throw new Error('O servidor não retornou um PDF válido.')
  }
  const blob = await response.blob()
  const signature = new TextDecoder().decode(await blob.slice(0, 5).arrayBuffer())
  if (signature !== '%PDF-') throw new Error('O servidor não retornou um PDF válido.')
  const disposition = response.headers.get('content-disposition') || ''
  const match = disposition.match(/filename\*?=(?:UTF-8''|["']?)([^"';]+)/i)
  const filename = match ? decodeURIComponent(match[1].replace(/["']/g, '')) : 'relatorio-viagem.pdf'
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename.endsWith('.pdf') ? filename : `${filename}.pdf`
    anchor.click()
  } finally { URL.revokeObjectURL(url) }
}

async function panelBlob(path: string): Promise<{blob: Blob; filename: string}> {
  const requestGeneration = panelSessionGeneration
  const response = await fetch(`${PANEL_API_URL}${path}`, { credentials: 'include' })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    if (response.status === 401 && requestGeneration === panelSessionGeneration) {
      window.dispatchEvent(new CustomEvent(ADMIN_SESSION_EXPIRED_EVENT, {
        detail: { returnPath: `${window.location.pathname}${window.location.search}` },
      }))
      throw new Error('Sua sessão expirou. Entre novamente.')
    }
    throw new Error(typeof payload?.detail === 'string'
      ? payload.detail
      : `Não foi possível gerar o relatório (${response.status}).`)
  }
  const contentType = response.headers.get('Content-Type') || ''
  if (!contentType.toLowerCase().startsWith('application/pdf')) {
    throw new Error('A API não retornou um PDF válido.')
  }
  const disposition = response.headers.get('Content-Disposition') || ''
  const filename = disposition.match(/filename="([^"]+)"/i)?.[1] || 'historico-motorista.pdf'
  return { blob: await response.blob(), filename }
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
  downloadTripReport: (tripKey: string) =>
    downloadPanelPdf(`/operations/trips/${encodeURIComponent(tripKey)}/report`),
  operationalAction: (tripKey: string, input: { action: 'finalize' | 'reopen' | 'undo_detection' | 'correct_times'; justification: string; operator?: string; corrections?: Record<string, string | null> }) =>
    panelRequest<OperationalTrip>(`/operations/trips/${encodeURIComponent(tripKey)}/actions`, {
      method: 'POST', body: JSON.stringify(input),
    }) as Promise<OperationalTrip>,
  tripLifecycle: (tripKey: string, action: 'cancel'|'archive'|'unarchive', reason: string) =>
    panelRequest<OperationalTrip>(`/operations/trips/${encodeURIComponent(tripKey)}/${action}`, {
      method: 'POST', body: JSON.stringify({ reason }),
    }) as Promise<OperationalTrip>,
  returnDecision: (candidateId: number, input: { decision: 'YES' | 'NO' | 'LATER'; operator?: string; justification?: string }) =>
    panelRequest<OperationalTrip>(`/operations/return-candidates/${candidateId}/decision`, {
      method: 'POST', body: JSON.stringify(input),
    }) as Promise<OperationalTrip>,
  trafficIncidents: () => request<TrafficSnapshot>('/traffic/incidents'),
  routePaths: () => request<RoutePaths>('/routes/paths'),
  operationalSites: () => request<OperationalSitesResponse>('/operational-sites'),
  createManualIncident: (input: Record<string, unknown>) => panelRequest('/traffic/manual', { method: 'POST', body: JSON.stringify(input) }),
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
  users: () => panelRequest<{users:ManagedUser[]}>('/api/users') as Promise<{users:ManagedUser[]}>,
  createUser: (input:{display_name:string;username:string;role:string;password:string}) => panelRequest<ManagedUser>('/api/users',{method:'POST',body:JSON.stringify(input)}) as Promise<ManagedUser>,
  updateUser: (id:string,input:{display_name?:string;role?:string}) => panelRequest<ManagedUser>(`/api/users/${id}`,{method:'PATCH',body:JSON.stringify(input)}) as Promise<ManagedUser>,
  resetUserPassword: (id:string,password:string) => panelRequest<ManagedUser>(`/api/users/${id}/reset-password`,{method:'POST',body:JSON.stringify({password})}) as Promise<ManagedUser>,
  setUserActive: (id:string,active:boolean) => panelRequest<ManagedUser>(`/api/users/${id}/${active?'activate':'deactivate'}`,{method:'POST'}) as Promise<ManagedUser>,
  observations: (tripKey:string) => panelRequest<{observations:OperationalObservation[]}>(`/operations/trips/${encodeURIComponent(tripKey)}/observations`) as Promise<{observations:OperationalObservation[]}>,
  createObservation: (tripKey:string,input:Record<string,unknown>) => panelRequest<OperationalObservation>(`/operations/trips/${encodeURIComponent(tripKey)}/observations`,{method:'POST',body:JSON.stringify(input)}) as Promise<OperationalObservation>,
  correctObservation: (id:string,input:{content:string;reason:string}) => panelRequest(`/operations/observations/${id}/correction`,{method:'POST',body:JSON.stringify(input)}),
  voidObservation: (id:string,reason:string) => panelRequest(`/operations/observations/${id}/void`,{method:'POST',body:JSON.stringify({reason})}),
  audit: (filters:Record<string,string>={}) => panelRequest<AuditResponse>(`/api/audit?${new URLSearchParams(filters)}`) as Promise<AuditResponse>,
  tripAudit: (tripKey:string) => panelRequest<AuditResponse>(`/operations/trips/${encodeURIComponent(tripKey)}/audit`) as Promise<AuditResponse>,
  driverHistory: (search='',page=1,pageSize=25) => panelRequest<Paged<DriverHistorySummary>>(`/api/driver-history/drivers?search=${encodeURIComponent(search)}&page=${page}&page_size=${pageSize}`) as Promise<Paged<DriverHistorySummary>>,
  driverProfile: (id:string) => panelRequest<DriverProfile>(`/api/driver-history/drivers/${encodeURIComponent(id)}`) as Promise<DriverProfile>,
  driverTrips: (id:string,query='') => panelRequest<Paged<DriverHistoryTrip>>(`/api/driver-history/drivers/${encodeURIComponent(id)}/trips${query?`?${query}`:''}`) as Promise<Paged<DriverHistoryTrip>>,
  pendingEvaluations: (query='') => panelRequest<Paged<PendingEvaluation>>(`/api/driver-history/pending-evaluations${query?`?${query}`:''}`) as Promise<Paged<PendingEvaluation>>,
  evaluateTrip: (tripKey:string,input:Record<string,unknown>) => panelRequest(`/api/driver-history/trips/${encodeURIComponent(tripKey)}/evaluation`,{method:'POST',body:JSON.stringify(input)}),
  adjustPunctuality: (tripKey:string,input:Record<string,unknown>) => panelRequest(`/api/driver-history/trips/${encodeURIComponent(tripKey)}/punctuality-adjustments`,{method:'POST',body:JSON.stringify(input)}),
  driverReport: (id:string,query='') => panelBlob(`/api/driver-history/drivers/${encodeURIComponent(id)}/report.pdf${query?`?${query}`:''}`),
}

export function trackingSocketUrl(): string {
  const currentOrigin = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  const base = (import.meta.env.VITE_WS_URL || (API_URL ? API_URL.replace(/^http/, 'ws') : currentOrigin)).replace(/\/$/, '')
  return `${base}/tracking/ws/manager`
}
