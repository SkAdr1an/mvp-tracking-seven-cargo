export interface PublicCoordinate {
  latitude: number
  longitude: number
}

export interface PublicTrip {
  driver_name: string
  route: {
    name?: string | null
    origin: { name: string; city?: string | null; state?: string | null; coordinate?: PublicCoordinate | null }
    destination: { name: string; city?: string | null; state?: string | null; coordinate?: PublicCoordinate | null }
    geometry: PublicCoordinate[]
    important_points: Array<{ name: string; coordinate: PublicCoordinate }>
  }
  public_status: string
  loaded_at?: string | null
  estimated_arrival_at?: string | null
  estimated_arrival_updated_at?: string | null
  last_updated_at: string
  stale: boolean
  finished: boolean
  vehicle: { plate: string; trailer_plate?: string | null }
  latest_position?: (PublicCoordinate & { recorded_at: string; speed_kmh?: number | null; source: string }) | null
  location_sources: {
    trafegus?: SourcePosition | null
    mobile?: SourcePosition | null
    difference_km?: number | null
    situation: 'TRAFEGUS_PRIMARY' | 'MOBILE_COMPLEMENTARY' | 'DIVERGENT' | 'NO_COMMUNICATION' | 'UNAVAILABLE'
  }
  mobile_location_enabled: boolean
  portal_alerts_enabled: boolean
  operational_instructions: string[]
  central_contact: { name: string; phone?: string | null }
  notices: Array<{ title: string; description: string; severity: string; updated_at: string }>
}

export interface SourcePosition extends PublicCoordinate {
  recorded_at: string
  speed_kmh?: number | null
  source: string
  accuracy_m?: number | null
  age_seconds: number
  status: 'CURRENT' | 'STALE'
}

export interface PortalAlert {
  id: string
  type: string
  severity: string
  distance_km?: number | null
  reference?: string | null
  updated_at: string
  source: string
  guidance: string
  description: string
  delay_minutes?: number | null
  distance_band: 'FIRST' | 'REINFORCEMENT'
  presentation: 'NEW' | 'ACTIVE' | 'UPDATED' | 'REINFORCED'
  latitude?: number | null
  longitude?: number | null
}

export interface PortalAlertsResponse {
  enabled: boolean
  alerts: PortalAlert[]
  integrations: Record<string, string>
  generated_at: string
}

export interface CachedPublicTrip {
  key: string
  data: PublicTrip
  synchronizedAt: string
}
