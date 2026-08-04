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
  operational_instructions: string[]
  central_contact: { name: string; phone?: string | null }
  notices: Array<{ title: string; description: string; severity: string; updated_at: string }>
}

export interface CachedPublicTrip {
  key: string
  data: PublicTrip
  synchronizedAt: string
}
