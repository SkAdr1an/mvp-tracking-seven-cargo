import { useEffect, useMemo } from 'react'
import { divIcon, latLngBounds, type LatLngExpression, type Map as LeafletMap } from 'leaflet'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import type { PortalAlert, PublicCoordinate, PublicTrip } from './types'
import {
  alertVisual, isValidCoordinate, mapPriorityCoordinates, splitRouteAtPosition,
} from './publicMapUtils'
import { locationAgeLabel } from './portalUtils'

const marker = (symbol: string, className: string, label: string) => divIcon({
  className: 'public-map-div-icon',
  html: `<span class="public-map-marker ${className}" role="img" aria-label="${label}">${symbol}</span>`,
  iconSize: [36, 36], iconAnchor: [18, 18], popupAnchor: [0, -18],
})

export function PublicTripMap({ trip, alerts = [] }: { trip: PublicTrip; alerts?: PortalAlert[] }) {
  const origin = isValidCoordinate(trip.route.origin.coordinate) ? trip.route.origin.coordinate : null
  const destination = isValidCoordinate(trip.route.destination.coordinate) ? trip.route.destination.coordinate : null
  const tracker = isValidCoordinate(trip.latest_position) ? trip.latest_position : null
  const mobile = isValidCoordinate(trip.location_sources?.mobile) ? trip.location_sources.mobile : null
  const position = tracker || mobile
  const geometry = trip.route.geometry.filter(isValidCoordinate)
  const routeParts = splitRouteAtPosition(geometry, position)
  const priority = mapPriorityCoordinates(trip)
  const validAlerts = alerts.filter((alert) => isValidCoordinate(alert as PublicCoordinate))
  const important = trip.route.important_points.filter((point) => isValidCoordinate(point.coordinate))
  const mapPoints = [
    ...priority,
    ...validAlerts.map((alert) => ({ latitude: alert.latitude!, longitude: alert.longitude! })),
    ...important.map((point) => point.coordinate),
  ]

  if (!mapPoints.length) return <UnavailableMap />
  const center = mapPoints[0]
  return <section className="public-card public-map-card" aria-labelledby="trip-map-title">
    <div className="public-section-title public-map-heading">
      <div><span>Rota da viagem</span><h2 id="trip-map-title">Acompanhamento no mapa</h2></div>
      {trip.stale && <strong className="public-map-stale">Posição antiga</strong>}
    </div>
    <div className="public-map-wrap">
      <MapContainer center={toLatLng(center)} zoom={position ? 8 : 6} className="public-map" scrollWheelZoom={false}>
        <TileLayer attribution="&copy; OpenStreetMap" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <MapViewport points={priority} position={position} />
        {routeParts.remaining.length > 1 && <Polyline positions={routeParts.remaining.map(toLatLng)} pathOptions={{ color: '#f3c623', weight: 6, opacity: .95 }} />}
        {routeParts.travelled.length > 1 && <Polyline positions={routeParts.travelled.map(toLatLng)} pathOptions={{ color: '#4f5b55', weight: 6, opacity: .95, dashArray: '8 7' }} />}
        {geometry.length > 1 && <DirectionMarker geometry={routeParts.remaining.length > 1 ? routeParts.remaining : geometry} />}
        {origin && <Marker position={toLatLng(origin)} icon={marker('O', 'public-map-marker--origin', 'Origem')}><Popup><strong>Origem</strong><br/>CD de origem — {trip.route.origin.name}<br/>{placeLocation(trip.route.origin)}</Popup></Marker>}
        {destination && <Marker position={toLatLng(destination)} icon={marker('D', 'public-map-marker--destination', 'Destino')}><Popup><strong>Destino</strong><br/>CD de destino — {trip.route.destination.name}<br/>{placeLocation(trip.route.destination)}</Popup></Marker>}
        {position && <Marker position={toLatLng(position)} icon={marker('🚚', `public-map-marker--vehicle${trip.stale ? ' is-stale' : ''}`, 'Veículo')}><Popup><strong>{tracker ? 'Posição atual do veículo' : 'Posição complementar do celular'}</strong><br/>{locationAgeLabel(position.recorded_at)}{mobile && !tracker && mobile.accuracy_m != null && <><br/>Precisão: {Math.round(mobile.accuracy_m)} m</>}</Popup></Marker>}
        {validAlerts.map((alert) => <AlertMarker key={alert.id} alert={alert} />)}
        {important.map((point) => <Marker key={`${point.name}-${point.coordinate.latitude}-${point.coordinate.longitude}`} position={toLatLng(point.coordinate)} icon={marker('•', 'public-map-marker--point', 'Ponto importante')}><Popup>{point.name}</Popup></Marker>)}
      </MapContainer>
      <MapLegend />
    </div>
    {!navigator.onLine && <p className="public-map-offline">O mapa-base pode ficar indisponível sem internet. A rota salva continua indicada.</p>}
  </section>
}

function UnavailableMap() {
  return <section className="public-card public-map-card public-map-unavailable" aria-labelledby="trip-map-title">
    <div className="public-section-title"><span>Rota da viagem</span><h2 id="trip-map-title">Localização ainda não disponível</h2></div>
    <p>O mapa será exibido quando a rota ou uma posição válida estiver disponível.</p>
  </section>
}

function MapViewport({ points, position }: { points: PublicCoordinate[]; position: PublicCoordinate | null }) {
  const map = useMap()
  const fit = () => fitPoints(map, points)
  useEffect(() => { fitPoints(map, points) }, [map, points])
  return <div className="public-map-controls leaflet-top leaflet-right">
    {position && <button type="button" onClick={() => map.setView(toLatLng(position), Math.max(map.getZoom(), 12))} aria-label="Centralizar no veículo">🚚</button>}
    {points.length > 1 && <button type="button" onClick={fit} aria-label="Ajustar à rota completa">⌗</button>}
  </div>
}

function fitPoints(map: LeafletMap, points: PublicCoordinate[]) {
  if (points.length > 1) map.fitBounds(latLngBounds(points.map(toLatLng)), { padding: [34, 34], maxZoom: 13 })
  else if (points[0]) map.setView(toLatLng(points[0]), 13)
}

function DirectionMarker({ geometry }: { geometry: PublicCoordinate[] }) {
  const middle = Math.max(0, Math.floor((geometry.length - 1) / 2))
  const from = geometry[middle]
  const to = geometry[Math.min(middle + 1, geometry.length - 1)]
  if (!from || !to) return null
  const angle = Math.atan2(to.longitude - from.longitude, -(to.latitude - from.latitude)) * 180 / Math.PI
  const icon = divIcon({ className: 'public-map-div-icon', html: `<span class="public-map-direction" style="transform:rotate(${angle}deg)">➤</span>`, iconSize: [24, 24], iconAnchor: [12, 12] })
  return <Marker position={toLatLng(from)} icon={icon} interactive={false} />
}

function AlertMarker({ alert }: { alert: PortalAlert }) {
  const visual = useMemo(() => alertVisual(alert), [alert])
  return <Marker position={[alert.latitude!, alert.longitude!]} icon={marker(visual.symbol, `public-map-alert ${visual.className}`, visual.label)}>
    <Popup><strong>{visual.label}</strong><br/>{alert.distance_km != null ? `Aproximadamente ${alert.distance_km} km` : 'Distância indisponível'}<br/>{locationAgeLabel(alert.updated_at)}<br/>{alert.guidance}</Popup>
  </Marker>
}

function MapLegend() {
  return <div className="public-map-legend" aria-label="Legenda do mapa"><span><i className="origin"/>Origem</span><span><i className="destination"/>Destino</span><span><i className="vehicle"/>Veículo</span><span><i className="travelled"/>Percorrido</span><span><i className="remaining"/>Restante</span><span><i className="alert"/>Alerta</span></div>
}

function toLatLng(point: PublicCoordinate): LatLngExpression { return [point.latitude, point.longitude] }
function placeLocation(place: PublicTrip['route']['origin']): string { return place.city && place.state ? `${place.city}/${place.state}` : place.city || place.state || 'Não informado' }
