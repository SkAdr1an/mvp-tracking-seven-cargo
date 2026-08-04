import { CircleMarker, MapContainer, Polyline, Popup, TileLayer } from 'react-leaflet'
import type { PublicTrip } from './types'

export function PublicTripMap({ trip }: { trip: PublicTrip }) {
  const origin = trip.route.origin.coordinate
  const destination = trip.route.destination.coordinate
  const position = trip.latest_position
  const mobilePosition = trip.location_sources?.mobile
  const center = position || mobilePosition || origin || destination || { latitude: -14.2, longitude: -51.9 }
  const geometry = trip.route.geometry.map((point) => [point.latitude, point.longitude] as [number, number])
  const hasMapData = Boolean(
    position || mobilePosition || origin || destination || geometry.length || trip.route.important_points.length,
  )
  if (!hasMapData) {
    return <section className="public-card public-map-card" aria-labelledby="trip-map-title">
      <div className="public-section-title">
        <span>Rota da viagem</span>
        <h2 id="trip-map-title">Mapa em atualização</h2>
      </div>
      <p>A localização ainda não está disponível. As demais informações da viagem continuam válidas.</p>
    </section>
  }
  return <section className="public-card public-map-card" aria-labelledby="trip-map-title">
    <div className="public-section-title">
      <span>Rota da viagem</span>
      <h2 id="trip-map-title">Acompanhamento no mapa</h2>
    </div>
    <MapContainer center={[center.latitude, center.longitude]} zoom={position ? 7 : 5} className="public-map" scrollWheelZoom={false}>
      <TileLayer attribution="&copy; OpenStreetMap" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {geometry.length > 1 && <Polyline positions={geometry} pathOptions={{ color: '#f3c623', weight: 5, opacity: .85 }} />}
      {origin && <CircleMarker center={[origin.latitude, origin.longitude]} radius={8} pathOptions={{ color: '#fff', fillColor: '#f3c623', fillOpacity: 1 }}><Popup><strong>Origem</strong><br/>CD de origem — {trip.route.origin.name}<br/>{placeLocation(trip.route.origin)}</Popup></CircleMarker>}
      {destination && <CircleMarker center={[destination.latitude, destination.longitude]} radius={8} pathOptions={{ color: '#fff', fillColor: '#858585', fillOpacity: 1 }}><Popup><strong>Destino</strong><br/>CD de destino — {trip.route.destination.name}<br/>{placeLocation(trip.route.destination)}</Popup></CircleMarker>}
      {position && <CircleMarker center={[position.latitude, position.longitude]} radius={10} pathOptions={{ color: '#fff', fillColor: '#111', fillOpacity: 1, weight: 3 }}><Popup>Posição atual do veículo</Popup></CircleMarker>}
      {mobilePosition && <CircleMarker center={[mobilePosition.latitude, mobilePosition.longitude]} radius={8} pathOptions={{ color: '#f3c623', fillColor: '#176b9c', fillOpacity: 1, weight: 3 }}><Popup>Posição complementar do celular<br/>Precisão: {mobilePosition.accuracy_m != null ? `${Math.round(mobilePosition.accuracy_m)} m` : 'indisponível'}</Popup></CircleMarker>}
      {trip.route.important_points.map((point) => <CircleMarker key={`${point.name}-${point.coordinate.latitude}-${point.coordinate.longitude}`} center={[point.coordinate.latitude, point.coordinate.longitude]} radius={6} pathOptions={{ color: '#f3c623', fillColor: '#444', fillOpacity: 1 }}><Popup>{point.name}</Popup></CircleMarker>)}
    </MapContainer>
    {!navigator.onLine && <p className="public-map-offline">O mapa-base pode ficar indisponível sem internet. A rota salva continua indicada.</p>}
  </section>
}

function placeLocation(place: PublicTrip['route']['origin']): string {
  return place.city && place.state ? `${place.city}/${place.state}` : place.city || place.state || 'Não informado'
}
