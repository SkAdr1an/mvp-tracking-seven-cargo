import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Driver } from '../types'
import { useDriverTracking } from './useDriverTracking'
import { validCoordinates, validDate } from '../dataSafety'

export function useFleetTracking() {
  const fleet = useQuery({
    queryKey: ['active-fleet'],
    queryFn: api.activeFleet,
    refetchInterval: 60_000,
    staleTime: 45_000,
    retry: 1,
  })
  const traffic = useQuery({ queryKey: ['traffic-incidents'], queryFn: api.trafficIncidents, refetchInterval: 60_000, staleTime: 45_000 })
  const paths = useQuery({ queryKey: ['route-paths'], queryFn: api.routePaths, refetchInterval: 60_000, staleTime: 45_000 })
  const sites = useQuery({ queryKey: ['operational-sites'], queryFn: api.operationalSites, staleTime: 5 * 60_000 })
  const websocket = useDriverTracking()
  const trafegusDrivers: Driver[] = (fleet.data?.trips || []).map((trip) => ({
    id: trip.plate,
    status: trip.stale ? 'offline' : 'on_route',
    location: trip.position && validCoordinates(trip.position.latitude, trip.position.longitude) ? { latitude: trip.position.latitude, longitude: trip.position.longitude, speed_kmh: Number.isFinite(trip.speed_kmh) ? trip.speed_kmh ?? undefined : undefined } : undefined,
    last_update: validDate(trip.communicated_at),
    trip_id: trip.trip_id || undefined,
    driver: trip.driver,
    trailer_plate: trip.trailer_plate || undefined,
    route: trip.route || trip.destination?.description,
    tracker: trip.tracker || undefined,
    stale: trip.stale,
    stale_minutes: trip.stale_minutes || undefined,
    location_description: trip.location_description || undefined,
    prediction: trip.prediction,
    weather_risks: Array.isArray(trip.weather_risks) ? trip.weather_risks.filter((risk) => validCoordinates(risk.position?.latitude, risk.position?.longitude)) : [],
    api_status: trip.api_status && typeof trip.api_status === 'object' ? trip.api_status : {},
    operational: trip.operational || undefined,
    route_progress: trip.route_progress || undefined,
    diagnostic: trip.diagnostic || undefined,
    operational_site: trip.operational_site || undefined,
    route_recognition: trip.route_recognition,
  }))
  const hasTrafegusSnapshot = fleet.data != null
  return {
    drivers: hasTrafegusSnapshot ? trafegusDrivers : websocket.drivers,
    connection: fleet.isFetching ? 'connecting' as const : fleet.isError ? websocket.connection : 'connected' as const,
    reconnect: () => { fleet.refetch(); websocket.reconnect() },
    fleet: fleet.data,
    source: hasTrafegusSnapshot ? 'trafegus' as const : 'websocket' as const,
    error: fleet.error,
    traffic: traffic.data,
    paths: paths.data,
    sites: sites.data?.sites || [],
    refreshTraffic: traffic.refetch,
  }
}
