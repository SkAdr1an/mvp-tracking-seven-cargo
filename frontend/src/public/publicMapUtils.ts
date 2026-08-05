import type { PortalAlert, PublicCoordinate, PublicTrip } from './types'

export function isValidCoordinate(value?: PublicCoordinate | null): value is PublicCoordinate {
  if (!value || !Number.isFinite(value.latitude) || !Number.isFinite(value.longitude)) return false
  if (value.latitude < -90 || value.latitude > 90 || value.longitude < -180 || value.longitude > 180) return false
  return value.latitude !== 0 || value.longitude !== 0
}

export function validCoordinates(values: Array<PublicCoordinate | null | undefined>): PublicCoordinate[] {
  return values.filter(isValidCoordinate)
}

export function splitRouteAtPosition(
  geometry: PublicCoordinate[], position?: PublicCoordinate | null,
): { travelled: PublicCoordinate[]; remaining: PublicCoordinate[] } {
  const route = geometry.filter(isValidCoordinate)
  if (route.length < 2 || !isValidCoordinate(position)) return { travelled: [], remaining: route }
  let nearest = 0
  let best = Number.POSITIVE_INFINITY
  route.forEach((point, index) => {
    const distance = (point.latitude - position.latitude) ** 2 + (point.longitude - position.longitude) ** 2
    if (distance < best) { best = distance; nearest = index }
  })
  return {
    travelled: route.slice(0, nearest + 1),
    remaining: route.slice(nearest),
  }
}

export function routeDistanceStats(geometry: PublicCoordinate[], position?: PublicCoordinate | null) {
  const split = splitRouteAtPosition(geometry, position)
  const length = (points: PublicCoordinate[]) => points.slice(1).reduce((total, point, index) => {
    const previous = points[index]
    const radius = 6371.0088
    const lat1 = previous.latitude * Math.PI / 180
    const lat2 = point.latitude * Math.PI / 180
    const dLat = lat2 - lat1
    const dLon = (point.longitude - previous.longitude) * Math.PI / 180
    const value = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
    return total + radius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value))
  }, 0)
  return { travelledKm: length(split.travelled), remainingKm: length(split.remaining) }
}

export function mapPriorityCoordinates(trip: PublicTrip): PublicCoordinate[] {
  const position = isValidCoordinate(trip.latest_position)
    ? trip.latest_position
    : isValidCoordinate(trip.location_sources?.mobile) ? trip.location_sources.mobile : null
  const route = trip.route.geometry.filter(isValidCoordinate)
  if (position && route.length) return validCoordinates([position, ...route])
  const endpoints = validCoordinates([trip.route.origin.coordinate, trip.route.destination.coordinate])
  if (endpoints.length) return endpoints
  return position ? [position] : route
}

export function alertVisual(alert: PortalAlert): { symbol: string; className: string; label: string } {
  const type = alert.type.toUpperCase()
  const base = type.includes('CHUVA') ? ['☔', 'weather', 'Chuva']
    : type.includes('CLIMA_NORMAL') ? ['☀', 'normal-weather', 'Clima normal']
    : type.includes('TRANSITO') ? ['≋', 'traffic', 'Trânsito']
      : type.includes('ACIDENTE') ? ['!', 'accident', 'Acidente']
        : type.includes('BLOQUEIO') || type.includes('INTERDICAO') ? ['×', 'blockage', 'Bloqueio']
          : type.includes('DESVIO') ? ['↪', 'deviation', 'Desvio']
            : ['!', 'other', alert.type.replaceAll('_', ' ')]
  const severity = alert.severity.toUpperCase() === 'CRITICO' ? 'critical' : 'attention'
  return { symbol: base[0], className: `public-map-alert--${base[1]} public-map-alert--${severity}`, label: base[2] }
}
