import type { HomologatedStation } from '../types'

export interface StationCluster {
  id: string
  latitude: number
  longitude: number
  stations: HomologatedStation[]
}

export function clusterStations(stations: HomologatedStation[], zoom: number): StationCluster[] {
  const validated = stations.filter((station) =>
    station.map_validation_status === 'validated'
    && Number.isFinite(station.latitude)
    && Number.isFinite(station.longitude)
  )
  if (zoom >= 12) return validated.map(singleton)
  const cellDegrees = Math.max(0.018, 22 / 2 ** Math.max(zoom, 1))
  const groups = new Map<string, HomologatedStation[]>()
  for (const station of validated) {
    const key = `${Math.floor((station.latitude + 90) / cellDegrees)}:${Math.floor((station.longitude + 180) / cellDegrees)}`
    groups.set(key, [...(groups.get(key) || []), station])
  }
  return [...groups.entries()].map(([key, values]) => ({
    id: `cluster:${zoom}:${key}`,
    latitude: average(values.map((value) => value.latitude)),
    longitude: average(values.map((value) => value.longitude)),
    stations: values,
  }))
}

function singleton(station: HomologatedStation): StationCluster {
  return { id: station.post_id, latitude: station.latitude, longitude: station.longitude, stations: [station] }
}

function average(values: number[]) {
  return values.reduce((total, value) => total + value, 0) / values.length
}
