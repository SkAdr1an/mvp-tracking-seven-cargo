import type { AngelLiraAdminResponse, AngelLiraStationsResponse, AuditResponse, DriverHistorySummary, DriverHistoryTrip, DriverImportPreview, DriverImportResult, DriverImportRow, DriverMasterResponse, DriverProfile, FleetSnapshot, IntegrationStatus, ManagedUser, OperationalObservation, OperationalSitesResponse, OperationalTrip, Paged, PanelSession, PendingEvaluation, PublicLinkCreated, PublicLinkStatus, RoutePaths, RoutePreview, TrafegusResult, TrafficSnapshot } from './types'
import type { DriverReportPreview } from './types'

const CONFIGURED_API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
// In development, route every browser request through Vite. Besides keeping the
// Strict HttpOnly cookie same-origin, this avoids CORS preflights against the API.
const API_URL = import.meta.env.DEV ? '' : CONFIGURED_API_URL
const PANEL_API_URL = API_URL
export const ADMIN_SESSION_EXPIRED_EVENT = 'seven:admin-session-expired'
export const PANEL_FORBIDDEN_EVENT = 'seven:panel-forbidden'
let panelSessionGeneration = 0
const SESSION_BOOTSTRAP_TIMEOUT_MS = 15_000

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
      if (typeof payload?.detail === 'string' && path.endsWith('/permanent-delete') && options?.method === 'POST') {
        throw new Error(payload.detail)
      }
      window.dispatchEvent(new CustomEvent(PANEL_FORBIDDEN_EVENT))
      throw new Error('Você não possui permissão para realizar esta ação.')
    }
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : `Falha na solicitação (${response.status})`)
  }
  if (response.status === 204) return null
  return response.json() as Promise<T>
}

async function downloadPanelPdf(path: string): Promise<void> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 70_000)
  let response: Response
  try {
    response = await fetch(`${PANEL_API_URL}${path}`, {
      method: 'POST', credentials: 'include', headers: { Accept: 'application/pdf' }, signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('A geração do PDF excedeu o tempo permitido. Tente novamente.')
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
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
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename.endsWith('.pdf') ? filename : `${filename}.pdf`
  anchor.hidden = true
  document.body.appendChild(anchor)
  anchor.click()
  window.setTimeout(() => {
    anchor.remove()
    URL.revokeObjectURL(url)
  }, 1_000)
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
  weeklyProgrammingSource: (force=false) => panelRequest<{csv:string;fetched_at:string;sheet_name:string;row_colors:Record<string,string>;cached:boolean}>(`/api/weekly-programming/source${force?'?force=true':''}`) as Promise<{csv:string;fetched_at:string;sheet_name:string;row_colors:Record<string,string>;cached:boolean}>,
  weeklyProgrammingState: () => panelRequest<{state:null|{week:string;file_name:string;sheet_name:string;rows:unknown[];imported_at:string;updated_at:string;online_fetched_at?:string}}>('/api/weekly-programming/state') as Promise<{state:null|{week:string;file_name:string;sheet_name:string;rows:unknown[];imported_at:string;updated_at:string;online_fetched_at?:string}}>,
  saveWeeklyProgrammingState: (input:{week:string;file_name:string;sheet_name:string;rows:unknown[];imported_at?:string;online_fetched_at?:string}) => panelRequest<{state:unknown}>('/api/weekly-programming/state',{method:'PUT',body:JSON.stringify(input)}) as Promise<{state:unknown}>,
  writebackWeeklyProgramming: (input:{lt:string;sheet_name:string;driver?:string|null;truck?:string|null;trailer?:string|null;phone?:string|null;cpf?:string|null;email?:string|null;driver_id?:string|null;event?:'FIELDS'|'DRIVER_SELECTED'|'ROUTE_RELEASED'}) => panelRequest<{writeback:{sheet_name:string;lt:string;updated_fields:string[]}}>('/api/weekly-programming/writeback',{method:'POST',body:JSON.stringify(input)}) as Promise<{writeback:{sheet_name:string;lt:string;updated_fields:string[]}}>,
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
  panelMe: () => panelRequest<PanelSession>('/api/auth/me', {
    signal: AbortSignal.timeout(SESSION_BOOTSTRAP_TIMEOUT_MS),
  }) as Promise<PanelSession>,
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
  permanentlyDeleteUser: (id:string,creatorPassword:string) => panelRequest<void>(`/api/users/${id}/permanent-delete`,{method:'POST',body:JSON.stringify({creator_password:creatorPassword})}) as Promise<void>,
  observations: (tripKey:string) => panelRequest<{observations:OperationalObservation[]}>(`/operations/trips/${encodeURIComponent(tripKey)}/observations`) as Promise<{observations:OperationalObservation[]}>,
  delayAccountability: () => panelRequest<{total:number;counts_by_responsibility:Record<string,number>;items:Array<OperationalObservation&{plate:string;driver?:string|null;route_id?:string|null}>}>('/operations/delay-accountability') as Promise<{total:number;counts_by_responsibility:Record<string,number>;items:Array<OperationalObservation&{plate:string;driver?:string|null;route_id?:string|null}>}>,
  operationalPlan: (tripKey:string) => panelRequest<{plan:OperationalTrip['plan']}>(`/operations/trips/${encodeURIComponent(tripKey)}/plan`) as Promise<{plan:OperationalTrip['plan']}>,
  updateOperationalPlan: (tripKey:string,input:Record<string,unknown>) => panelRequest<NonNullable<OperationalTrip['plan']>>(`/operations/trips/${encodeURIComponent(tripKey)}/plan`,{method:'PUT',body:JSON.stringify(input)}) as Promise<NonNullable<OperationalTrip['plan']>>,
  createObservation: (tripKey:string,input:Record<string,unknown>) => panelRequest<OperationalObservation>(`/operations/trips/${encodeURIComponent(tripKey)}/observations`,{method:'POST',body:JSON.stringify(input)}) as Promise<OperationalObservation>,
  correctObservation: (id:string,input:{content:string;reason:string}) => panelRequest(`/operations/observations/${id}/correction`,{method:'POST',body:JSON.stringify(input)}),
  voidObservation: (id:string,reason:string) => panelRequest(`/operations/observations/${id}/void`,{method:'POST',body:JSON.stringify({reason})}),
  audit: (filters:Record<string,string>={}) => panelRequest<AuditResponse>(`/api/audit?${new URLSearchParams(filters)}`) as Promise<AuditResponse>,
  tripAudit: (tripKey:string) => panelRequest<AuditResponse>(`/operations/trips/${encodeURIComponent(tripKey)}/audit`) as Promise<AuditResponse>,
  driverHistory: (search='',page=1,pageSize=25) => panelRequest<Paged<DriverHistorySummary>>(`/api/driver-history/drivers?search=${encodeURIComponent(search)}&page=${page}&page_size=${pageSize}`) as Promise<Paged<DriverHistorySummary>>,
  driverMaster: (filters:Record<string,string|number>) => panelRequest<DriverMasterResponse>(`/api/driver-history/master?${new URLSearchParams(Object.entries(filters).map(([key,value])=>[key,String(value)]))}`) as Promise<DriverMasterResponse>,
  previewDriverImport: (payload:{file_name:string;rows:DriverImportRow[]}) => panelRequest<DriverImportPreview>('/api/driver-history/master/import/preview',{method:'POST',body:JSON.stringify(payload)}),
  importDrivers: (payload:{file_name:string;rows:DriverImportRow[]}) => panelRequest<DriverImportResult>('/api/driver-history/master/import',{method:'POST',body:JSON.stringify(payload)}),
  driverProfile: (id:string) => panelRequest<DriverProfile>(`/api/driver-history/drivers/${encodeURIComponent(id)}`) as Promise<DriverProfile>,
  driverTrips: (id:string,query='') => panelRequest<Paged<DriverHistoryTrip>>(`/api/driver-history/drivers/${encodeURIComponent(id)}/trips${query?`?${query}`:''}`) as Promise<Paged<DriverHistoryTrip>>,
  driverReportPreview: (tripKey:string) => panelRequest<DriverReportPreview>(`/api/driver-history/trips/${encodeURIComponent(tripKey)}/report-preview`) as Promise<DriverReportPreview>,
  correctDriverReport: (tripKey:string,input:{field:string;value:string;justification:string}) => panelRequest<DriverReportPreview>(`/api/driver-history/trips/${encodeURIComponent(tripKey)}/report-corrections`,{method:'POST',body:JSON.stringify(input)}) as Promise<DriverReportPreview>,
  createDriverReportNote: (tripKey:string,input:{content:string;attachments:Array<{name:string;mime_type:'image/jpeg'|'image/png';data_base64:string}>}) => panelRequest(`/api/driver-history/trips/${encodeURIComponent(tripKey)}/report-notes`,{method:'POST',body:JSON.stringify(input)}),
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
