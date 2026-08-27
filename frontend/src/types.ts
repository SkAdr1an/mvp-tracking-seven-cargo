export type DriverStatus = 'online' | 'on_route' | 'paused' | 'offline'

export interface DriverLocation {
  latitude: number
  longitude: number
  speed_kmh?: number
  heading?: number
  battery_level?: number
  signal_strength?: number
  timestamp?: string
}

export interface Driver {
  id: string
  status: DriverStatus
  location?: DriverLocation
  last_update?: string
  trip_id?: string
  driver?: string
  trailer_plate?: string
  route?: string
  tracker?: string
  stale?: boolean
  stale_minutes?: number
  location_description?: string
  prediction?: FleetPrediction
  weather_risks?: WeatherRisk[]
  api_status?: Record<string, string>
  operational?: OperationalTrip
  route_progress?: RouteProgress
  diagnostic?: OperationalDiagnostic
  operational_site?: VehicleOperationalSite
  route_recognition?: RouteRecognition
}

export interface VehicleOperationalSite {
  site_id?: string | null
  site_name?: string | null
  operation?: string | null
  state: 'INSIDE' | 'APPROACHING' | 'OUTSIDE' | 'UNAVAILABLE'
  distance_m?: number | null
  position_at?: string | null
  diagnostic?: {
    reason?: string
    nearest_site?: string
    overlap_candidates?: string[]
    hysteresis_preserved?: boolean
    confirmed_exit?: boolean
  }
}

export interface OperationalSite {
  id: string
  name: string
  operation: string
  address?: string | null
  municipality?: string | null
  latitude: number
  longitude: number
  approach_radius_m: number
  entry_radius_m: number
  exit_radius_m: number
  active: boolean
  aliases: string[]
}

export interface OperationalSitesResponse {
  sites: OperationalSite[]
  states: Array<VehicleOperationalSite & { plate: string }>
}

export interface IntegrationStatus {
  tomtom: string
  openweather: string
  location: string
  temperature_c: number | null
  weather: string | null
  trafegus?: string
  trafegus_detail?: { status:string;last_success_at?:string|null;last_error_at?:string|null;message?:string|null;http_status?:number|null;request_count?:number|null;interval_seconds?:number }
  note?: string
  tomtom_routing?: string
  tomtom_traffic_incidents?: string
  tomtom_traffic_flow?: string
  azure_maps_traffic_incidents?: string
}

export interface FleetPrediction {
  status: string
  classification?: 'NORMAL' | 'ATENCAO' | 'CRITICA'
  remaining_distance_km?: number
  remaining_minutes?: number
  live_traffic_delay_minutes?: number
  eta_at?: string
  sla_at?: string | null
  delay_minutes?: number | null
  sla_margin_minutes?: number | null
  reason?: string
}

export interface WeatherRisk {
  type: string
  severity: string
  description: string
  passage_at: string
  position: { latitude: number; longitude: number }
  temperature_c?: number
  rain_3h_mm?: number
  visibility_m?: number
  source: string
}

export interface FleetTrip {
  trip_id?: string | null
  plate: string
  trailer_plate?: string | null
  driver: string
  route?: string | null
  position?: { latitude: number; longitude: number } | null
  speed_kmh?: number | null
  location_description?: string | null
  communicated_at?: string | null
  stale: boolean
  stale_minutes?: number | null
  status: string
  tracker?: string | null
  destination?: { description: string; position: { latitude: number; longitude: number } } | null
  sla_at?: string | null
  prediction: FleetPrediction
  weather_risks: WeatherRisk[]
  api_status: Record<string, string>
  current_driver?: string | null
  previous_driver?: string | null
  driver_source?: string | null
  driver_divergence?: boolean
  driver_changed?: boolean
  operational?: OperationalTrip | null
  route_progress?: RouteProgress | null
  diagnostic?: OperationalDiagnostic | null
  operational_site?: VehicleOperationalSite | null
  route_recognition?: RouteRecognition
}

export interface RouteRecognition {
  status: 'RECOGNIZED' | 'UNIDENTIFIED' | 'AMBIGUOUS' | 'GEOMETRY_PENDING'
  method: string
  reason: string
}

export interface OperationalDiagnostic {
  trip_key: string
  eta_at?: string | null
  window_start_at?: string | null
  window_end_at?: string | null
  client_eta_at?: string | null
  commitment_delta_minutes?: number | null
  trend: 'ADIANTADO'|'DENTRO_DO_PRAZO'|'RISCO_DE_ATRASO'|'PROVAVEL_ATRASO'|'SEM_COMPROMISSO'
  confidence: 'HIGH'|'MEDIUM'|'LOW'
  classification?: 'NORMAL'|'ATENCAO'|'CRITICA'|null
  remaining_minutes?: number|null
  stopped_minutes: number
  method_version: string
  factors: Array<{code:string;label:string;value?:number|null;minutes?:number}>
  confidence_reasons: string[]
  risks: Array<{type:string;severity:string;description:string;delay_minutes?:number;return_distance_km?:number;stopped_minutes?:number}>
  recommendations: string[]
  scenarios: Record<'optimistic'|'likely'|'conservative',{eta_at:string;explanation:string}>
  status_explanation: string
  calculated_at: string
  angellira_context?: AngelLiraDiagnosticContext | null
}

export interface RouteProgress { geometry_version:string;route_variant?:string|null;route_variant_name?:string|null;alternative_route?:boolean;total_distance_km:number;advanced_distance_km:number;remaining_distance_km:number;progress_percent:number;return_distance_km?:number|null;route_state:'ON_ROUTE'|'OUTSIDE'|'STALE';confidence:'HIGH'|'MEDIUM'|'LOW'|'UNAVAILABLE';position_at?:string|null;speed_kmh?:number|null;speed_state:'CURRENT'|'STALE'|'UNAVAILABLE';reason?:string }

export type OperationalState = 'PROGRAMADA' | 'NA_ORIGEM' | 'EM_CARREGAMENTO' | 'EM_VIAGEM' | 'NO_DESTINO' | 'FINALIZADA_NO_SISTEMA' | 'REABERTA_MANUALMENTE' | 'RETORNO_SEVEN_CONFIRMADO' | 'RETORNO_CONCLUIDO' | 'CANCELADA'

export interface ReturnCandidate {
  id: number
  parent_trip_key: string
  state: 'AGUARDANDO_CONFIRMACAO' | 'RETORNO_SEVEN_CONFIRMADO' | 'RETORNO_EXTERNO' | 'RETORNO_CONCLUIDO'
  arrival_at: string
  departure_at: string
  destination_stay_hours: number
  progress_toward_origin_km: number
  corridor_distance_m: number
  compatible_with_route: boolean
  evidence: Record<string, unknown>
  decision?: 'YES' | 'NO' | 'LATER' | null
  decision_at?: string | null
  decided_by?: string | null
  justification?: string | null
  return_trip_key?: string | null
}

export interface OperationalEvent {
  id: number
  event_type: string
  occurred_at: string
  source: string
  description: string
  previous_state?: string | null
  new_state?: string | null
  metadata?: Record<string, unknown>
  justification?: string | null
  operator?: string | null
}

export interface OperationalRoute {
  id: string
  name: string
  origin_name: string
  destination_name: string
  origin_latitude: number
  origin_longitude: number
  destination_latitude: number
  destination_longitude: number
  origin_radius_m: number
  destination_radius_m: number
  active: boolean
}

export interface OperationalTrip {
  trip_key: string
  provider_trip_id?: string | null
  plate: string
  route_id?: string | null
  state: OperationalState
  current_driver?: string | null
  previous_driver?: string | null
  driver_source?: string | null
  driver_divergence: boolean
  origin_entered_at?: string | null
  arrived_origin_at?: string | null
  started_at?: string | null
  destination_entered_at?: string | null
  arrived_destination_at?: string | null
  finished_at?: string | null
  finish_type?: 'automatic' | 'manual' | null
  cancelled_at?: string | null
  cancelled_by_user_id?: string | null
  cancelled_reason?: string | null
  archived_at?: string | null
  archived_by_user_id?: string | null
  archive_reason?: string | null
  route?: OperationalRoute | null
  events?: OperationalEvent[]
  stops?: { id: number; started_at?: string | null; ended_at?: string | null }[]
  geofences?: {
    origin: 'inside' | 'outside' | 'unknown'
    destination: 'inside' | 'outside' | 'unknown'
    origin_distance_m?: number
    destination_distance_m?: number
    time_inside_minutes?: number | null
  }
  return_candidate?: ReturnCandidate | null
  return_trip?: OperationalTrip | null
  plan?: {scheduled_start_at?:string|null;scheduled_arrival_at?:string|null;customer_commitment_at?:string|null;planned_loading_minutes?:number;planned_stops_minutes?:number;operational_buffer_minutes?:number;source?:'SEVEN'|'CLIENT'|'TRAFEGUS';notes?:string|null}|null
}

export interface PanelSession {
  authenticated: true
  user_id?: string | null
  username: string
  display_name: string
  role: string
  permissions: string[]
  expires_at?: string | null
}

export interface ManagedUser { id:string;username:string;display_name:string;role:'ADMIN'|'GR'|'MONITORING';status:'ACTIVE'|'INACTIVE';created_at:string;updated_at:string;last_login?:string|null;permissions:string[] }
export interface OperationalObservation { id:string;trip_key:string;type:'GENERAL'|'STOP'|'DRIVER_CONTACT'|'GR_INTERVENTION'|'INCIDENT'|'OPERATIONAL_NOTE';type_label:string;content:string;occurred_at:string;created_at:string;status:'ACTIVE'|'CORRECTED'|'VOIDED';include_in_report:boolean;stop_id?:number|null;author:{user_id:string;username:string;display_name:string;role:string;role_label:string};correction?:{supersedes_observation_id?:string|null;reason?:string|null}|null;void?:{reason?:string|null}|null;metadata?:{delay_category?:string;responsibility?:string;critical_impact?:boolean}|null }

export interface PublicLinkStatus {
  id: string
  created_at: string
  expires_at?: string | null
  revoked_at?: string | null
  active: boolean
  last_access_at?: string | null
  access_count: number
  created_by?: string | null
}

export interface PublicLinkCreated {
  id: string
  url: string
  created_at: string
  expires_at?: string | null
  active: boolean
}

export interface FleetSnapshot {
  source: 'trafegus'
  source_status: string
  generated_at: string
  counts: { total: number; normal: number; attention: number; critical: number; stale: number; weather_risks: number }
  trips: FleetTrip[]
  warning?: string
  cache?: { hit: boolean; stale?: boolean; age_seconds: number }
}

export type IncidentCategory = 'ACIDENTE'|'CONGESTIONAMENTO'|'TRANSITO_LENTO'|'OBRA'|'INTERDICAO'|'VIA_FECHADA'|'VEICULO_PARADO'|'RISCO_VIA'|'RISCO_CLIMATICO'|'OCORRENCIA_MANUAL'|'OUTRO'
export interface TrafficIncident { id:string;route_id:string;category:IncidentCategory;severity:'INFORMATIVO'|'ATENCAO'|'CRITICO';original_type?:string;source:string;description:string;road_name?:string;direction?:string;latitude:number;longitude:number;geometry:{type:string;coordinates:unknown};length_m?:number;delay_seconds?:number;delay_already_in_eta:boolean;started_at?:string;updated_at:string;expires_at:string;status:string;manual:boolean;information_source?:string;responsible_user?:string;affected_vehicles:Array<{trip_key?:string;plate?:string;distance_along_route_km:number;severity:string;reported_delay_seconds?:number;eta_adjustment_applied:boolean}> }
export interface TrafficRoute { id:string;name:string;origin_name:string;destination_name:string;origin_latitude:number;origin_longitude:number;destination_latitude:number;destination_longitude:number;origin_radius_m:number;destination_radius_m:number;geometry:Array<{latitude:number;longitude:number}>;alternative_geometries?:Array<{id:string;name:string;version:string;geometry:Array<{latitude:number;longitude:number}>}>;geometry_version?:string|null;geometry_source?:string|null;geometry_provider?:string|null;distance_m?:number|null;duration_seconds?:number|null }
export interface TrafficSnapshot { incidents:TrafficIncident[];counts:{ACIDENTE:number;OBRA_INTERDICAO:number;TRECHO_LENTO:number;RISCO_CLIMATICO:number;MANUAL:number};snapshot?:{collected_at:string;status:string;request_count:number;incident_count:number};routes:TrafficRoute[];generated_at:string }

export interface RouteDeviation { id:number;trip_key:string;plate:string;route_id:string;status:string;level:'INITIAL'|'MODERATE'|'MAXIMUM';started_at:string;current_distance_m:number;max_distance_m:number;exit_latitude:number;exit_longitude:number;acknowledged_at?:string|null;reason?:string|null;justification?:string|null;related_incidents:string[] }
export interface VehiclePath { trip_key:string;plate:string;route_id?:string|null;segments:Array<Array<{latitude:number;longitude:number;recorded_at:string;speed_kmh?:number|null}>>;outliers?:Array<{id:number;recorded_at:string;reason:string}>;raw_position_count?:number;derived_position_count?:number;deviation?:RouteDeviation|null }
export interface RoutePaths { paths:VehiclePath[] }

export interface RoutePreview {
  origin: { address: string; position: { lat: number; lon: number } }
  destination: { address: string; position: { lat: number; lon: number } }
  departure_at: string
  distance_km: number
  duration_without_traffic_minutes: number
  duration_with_traffic_minutes: number
  traffic_delay_minutes: number
  live_traffic_delay_minutes: number
  traffic_length_km: number
  estimated_arrival_at: string
  status: 'normal' | 'attention' | 'critical'
  operational_speed_min_kmh?: number
  operational_speed_max_kmh?: number
  average_operational_speed_kmh?: number
  operational_duration_minutes?: number
  operational_arrival_at?: string
  waypoints?: RouteWaypoint[]
  timeline?: RouteTimelineItem[]
  risk_factors?: RouteRiskFactor[]
  assumptions?: string[]
  data_freshness?: string
}

export interface RouteWaypoint {
  name?: string
  address?: string
  type?: string
  sequence?: number
  estimated_arrival_at?: string
  stop_duration_minutes?: number
}

export interface RouteTimelineItem {
  title?: string
  description?: string
  type?: string
  distance_from_origin_km?: number
  estimated_arrival_at?: string
  delay_minutes?: number
}

export interface RouteRiskFactor {
  type?: string
  title?: string
  description?: string
  severity?: 'low' | 'medium' | 'high' | string
  source?: string
  updated_at?: string
  delay_minutes?: number
}

export interface TrafegusResult {
  plate: string
  vehicle: ProviderResult
  last_position: ProviderResult
  events: ProviderResult
  trip: ProviderResult
}

export interface ProviderResult {
  ok: boolean
  http_status: number
  data?: Record<string, unknown>
  error?: string
}

export type AngelLiraValidationStatus = 'validated'|'probable'|'pending_review'|'rejected'|'not_geocoded'|'not_available'

export interface HomologatedStation {
  post_id: string
  canonical_name: string
  city: string
  uf: string
  road?: string|null
  km?: string|number|null
  phone?: string|null
  latitude: number
  longitude: number
  map_validation_status: 'validated'
  source_name?: string
  source_version?: string
}

export interface AngelLiraDataset {
  dataset_id: string
  source_name: string
  source_version: string
  imported_at?: string|null
  counts?: Record<string,number>
}

export interface AngelLiraStationsResponse {
  source: string
  dataset: AngelLiraDataset|null
  stations: HomologatedStation[]
}

export interface AngelLiraReviewItem {
  id?: string
  post_id?: string
  risk_area_id?: string
  exact_group_id?: string
  kind?: 'station'|'station_variant'|'risk_area'
  name?: string
  canonical_name?: string
  representative_name?: string
  city?: string|null
  uf?: string|null
  road?: string|null
  status?: AngelLiraValidationStatus|string
  map_validation_status?: string|null
  reason?: string|null
  data_quality_reason?: string|null
  candidate_reason?: string|null
  geometry_validation_status?: string|null
}

export interface AngelLiraAdminResponse {
  status: {
    dataset: AngelLiraDataset|null
    stations: {total:number;by_status:Record<string,number>;visible:number}
    risk_areas: {total:number;validated_geometries:number;visible:number;dwell_eligible:number}
  }
  review_queue: {
    stations: AngelLiraReviewItem[]
    variants: AngelLiraReviewItem[]
    risk_areas: AngelLiraReviewItem[]
  }
}

export interface AngelLiraDiagnosticContext {
  source_name: string
  source_version: string
  nearby_station?: Pick<HomologatedStation,'post_id'|'canonical_name'|'city'|'uf'|'road'|'km'> & { distance_m?:number|null }
  risk_area?: { id:string;name:string;dwell_minutes?:number|null;geometry_validation_status:'validated';message:string }
  conflict_resolution?: string|null
}

export interface AuditEvent {
  id:string; occurred_at:string; actor_user_id?:string|null
  actor_username_snapshot:string; actor_display_name_snapshot:string; actor_role_snapshot:string
  action_type:string; resource_type:string; resource_id?:string|null; trip_key?:string|null
  before?:Record<string,unknown>|null; after?:Record<string,unknown>|null
  content?:string|null; justification?:string|null; metadata?:Record<string,unknown>|null
}
export interface AuditResponse { events:AuditEvent[]; next_cursor?:string|null }

export type Page = 'overview' | 'drivers' | 'driver-history' | 'pending-evaluations' | 'routes' | 'trafegus' | 'integrations' | 'angellira' | 'users' | 'audit'

export interface DriverHistorySummary { id:string;cpf_masked?:string|null;identity_status?:'PENDING'|'VERIFIED';name:string;phone?:string|null;total_trips:number;finished_trips:number;active_trips:number;pending_evaluations:number;last_trip_at?:string|null }
export interface DriverHistoryTrip { trip_key:string;provider_trip_id?:string|null;driver_id:string;plate:string;trailer_plate?:string|null;route_id?:string|null;route_name?:string|null;origin_name?:string|null;destination_name?:string|null;customer?:string|null;status:string;source_created_at?:string|null;loaded_at?:string|null;started_at?:string|null;scheduled_arrival_at?:string|null;eta_at?:string|null;arrived_destination_at?:string|null;finished_at?:string|null;package_count?:number|null;responsible?:string|null;automatic_punctuality:string;considered_punctuality?:string|null;evaluation_status:string }
export interface DriverProfile extends DriverHistorySummary { cancelled_trips:number;automatic_punctuality_percent?:number|null;considered_punctuality_percent?:number|null;routes:Array<{route_name:string;trips:number}>;customers:Array<{customer:string;trips:number}>;evaluations:Array<Record<string,unknown>>;notes:Array<Record<string,unknown>> }
export interface PendingEvaluation extends DriverHistoryTrip { driver_name:string;pending_hours:number;situation:'PENDING'|'OVERDUE' }
export interface Paged<T> { items:T[];page:number;page_size:number;total:number;overdue_hours?:number }

