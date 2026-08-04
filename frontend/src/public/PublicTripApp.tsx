import {
  AlertTriangle, ArrowRight, CalendarClock, Clock3, MapPin, MessageCircle, Navigation, RefreshCw,
  Satellite, ShieldCheck, Smartphone, Truck, UserRound, Wifi, WifiOff,
} from 'lucide-react'
import { PublicTripMap } from './PublicTripMap'
import { usePublicTrip } from './hooks/usePublicTrip'
import type { PublicTripFailureReason } from './errors'
import type { PublicTrip } from './types'
import { buildCentralWhatsAppUrl, locationAgeLabel } from './portalUtils'

export function PublicTripApp({ token }: { token: string }) {
  const state = usePublicTrip(token)
  if (state.invalid) return <InvalidPublicTrip reason={state.terminalReason} />
  if (state.loading && !state.record) return <PublicShell><div className="public-state"><RefreshCw className="spin" /><h1>Carregando sua viagem</h1><p>Buscando as informações mais recentes.</p></div></PublicShell>
  if (!state.record) {
    const offline = !state.online
    return <PublicShell><div className="public-state">
      {offline ? <WifiOff /> : <AlertTriangle />}
      <h1>{offline ? 'Você está sem internet' : 'Não foi possível acessar a Central Seven Cargo'}</h1>
      <p>{offline
        ? 'Conecte-se à internet para abrir esta viagem pela primeira vez.'
        : 'A internet está disponível, mas a Central não respondeu. Tente novamente em alguns instantes.'}</p>
      <button onClick={() => void state.refresh()} disabled={state.refreshing || offline}>
        <RefreshCw className={state.refreshing ? 'spin' : ''} /> {state.refreshing ? 'Tentando' : 'Tentar novamente'}
      </button>
    </div></PublicShell>
  }

  const trip = state.record.data
  return <PublicShell>
    <header className="public-header">
      <Brand />
      <div className={`public-connection ${state.online ? 'is-online' : 'is-offline'}`}>
        {state.online ? <Wifi /> : <WifiOff />}
        <span>{state.online ? 'Online' : 'Offline'}</span>
      </div>
    </header>
    {!state.online && <div className="public-offline-banner" role="status"><WifiOff /><span>Você está sem internet. Mostrando dados da última atualização.</span></div>}
    {state.error && state.online && <div className="public-warning" role="status"><AlertTriangle /><span>Não foi possível buscar uma atualização. As últimas informações válidas foram mantidas.</span></div>}

    <main className="public-main">
      <section className="public-hero">
        <div>
          <span className="public-eyebrow">Portal da viagem</span>
          <h1>Olá, {firstName(trip.driver_name)}</h1>
          <p>Acompanhe abaixo as informações importantes da sua viagem.</p>
        </div>
        <span className="public-status">{trip.public_status}</span>
      </section>

      <section className="public-route-card">
        <RoutePoint label="CD de origem" place={trip.route.origin} />
        <div className="public-route-line" aria-label="Sentido da viagem"><i /><span>sentido da viagem</span><ArrowRight /><i /></div>
        <RoutePoint label="CD de destino" place={trip.route.destination} destination />
      </section>

      <section className="public-summary-grid">
        <Summary icon={<Navigation />} label="Situação atual" value={trip.public_status} />
        <Summary
          icon={<Clock3 />}
          label="Previsão de chegada"
          value={trip.estimated_arrival_at
            ? formatDateTime(trip.estimated_arrival_at)
            : 'Previsão em atualização pela Central Seven Cargo.'}
        />
        <Summary icon={<CalendarClock />} label="Carregamento" value={formatDateTime(trip.loaded_at)} />
        <Summary icon={<Truck />} label="Veículo" value={`${trip.vehicle.plate}${trip.vehicle.trailer_plate ? ` · ${trip.vehicle.trailer_plate}` : ''}`} />
        <Summary icon={<UserRound />} label="Motorista" value={trip.driver_name} />
      </section>

      {trip.stale && <div className="public-stale"><AlertTriangle /><div><strong>Localização desatualizada</strong><span>A última posição pode não representar o local atual do veículo.</span></div></div>}

      <section className="public-card public-location-status" aria-labelledby="location-status-title">
        <header><Satellite /><div><span>Última localização recebida</span><h2 id="location-status-title">{trip.latest_position ? 'Disponível no mapa' : 'Localização indisponível'}</h2></div></header>
        <div className="public-location-details">
          <div><span>Fonte</span><strong>{trip.latest_position?.source || 'Não informada'}</strong></div>
          <div><span>Horário</span><strong>{formatDateTime(trip.latest_position?.recorded_at || trip.last_updated_at)}</strong></div>
          <div><span>Idade da posição</span><strong className={trip.stale ? 'is-stale' : ''}>{locationAgeLabel(trip.latest_position?.recorded_at || trip.last_updated_at)}</strong></div>
        </div>
      </section>

      <PublicTripMap key={token} trip={trip} />

      {trip.route.important_points.length > 0 && <InfoSection icon={<MapPin />} title="Pontos importantes">
        {trip.route.important_points.map((point) => <p key={point.name}>{point.name}</p>)}
      </InfoSection>}
      {trip.operational_instructions.length > 0 && <InfoSection icon={<ShieldCheck />} title="Instruções operacionais">
        {trip.operational_instructions.map((instruction) => <p key={instruction}>{instruction}</p>)}
      </InfoSection>}
      <InfoSection icon={<AlertTriangle />} title="Próximos alertas" warning>
        {trip.notices.length > 0
          ? trip.notices.map((notice) => <article key={`${notice.title}-${notice.updated_at}`}><strong>{notice.title}</strong><p>{notice.description}</p><small>Atualizado em {formatDateTime(notice.updated_at)}</small></article>)
          : <p>Nenhum alerta confirmado à frente neste momento.</p>}
      </InfoSection>

      <section className="public-card public-sharing" aria-labelledby="sharing-title">
        <Smartphone />
        <div><span>Compartilhamento pelo celular</span><h2 id="sharing-title">Não iniciado</h2><p>O envio voluntário de localização será disponibilizado somente após seu consentimento. A página deverá permanecer aberta durante o compartilhamento.</p></div>
        <span className="public-sharing-badge">Inativo</span>
      </section>

      <section className="public-card public-contact">
        <div><MessageCircle /><div><span>Precisa de ajuda?</span><strong>{trip.central_contact.name}</strong></div></div>
        <a href={buildCentralWhatsAppUrl()} target="_blank" rel="noopener noreferrer"><MessageCircle /> WhatsApp Central</a>
      </section>

      <footer className="public-footer">
        <div><Navigation /><span>Última sincronização<br/><strong>{formatDateTime(state.record.synchronizedAt)}</strong></span></div>
        <button onClick={() => void state.refresh()} disabled={state.refreshing || !state.online}>
          <RefreshCw className={state.refreshing ? 'spin' : ''} /> {state.refreshing ? 'Atualizando' : 'Atualizar'}
        </button>
      </footer>
    </main>
  </PublicShell>
}

export function InvalidPublicTrip({ reason = 'invalid_token' }: { reason?: PublicTripFailureReason }) {
  const content = {
    invalid_token: ['Link de viagem inválido', 'Confira o endereço recebido ou entre em contato com a Central Seven Cargo.'],
    expired: ['Este link expirou', 'Solicite um novo link de acompanhamento à Central Seven Cargo.'],
    revoked: ['Link indisponível', 'Este link não está mais disponível. Entre em contato com a Central Seven Cargo.'],
    trip_finished: ['Viagem finalizada', 'Esta viagem foi concluída e o link de acompanhamento não está mais disponível.'],
  }[reason]
  return <PublicShell><div className="public-state public-state--invalid"><AlertTriangle /><h1>{content[0]}</h1><p>{content[1]}</p></div></PublicShell>
}

function PublicShell({ children }: { children: React.ReactNode }) {
  return <div className="public-trip-shell">{children}</div>
}

function Brand() {
  return <div className="public-brand"><div className="public-brand-mark">7</div><div><strong>Seven Cargo</strong><span>Portal do motorista</span></div></div>
}

function RoutePoint({ label, place, destination = false }: {
  label: string
  place: PublicTrip['route']['origin']
  destination?: boolean
}) {
  const location = place.city && place.state
    ? `${place.city}/${place.state}`
    : place.city || place.state || 'Não informado'
  return <div className="public-route-point"><i className={destination ? 'destination' : ''}><MapPin /></i><div><span>{label}</span><strong>{place.name || 'Não informado'}</strong><small>{location}</small></div></div>
}

function Summary({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <article className="public-summary"><i>{icon}</i><div><span>{label}</span><strong>{value}</strong></div></article>
}

function InfoSection({ icon, title, warning = false, children }: { icon: React.ReactNode; title: string; warning?: boolean; children: React.ReactNode }) {
  return <section className={`public-card public-info ${warning ? 'public-info--warning' : ''}`}><header>{icon}<h2>{title}</h2></header><div>{children}</div></section>
}

function formatDateTime(value?: string | null): string {
  if (!value) return 'Não informado'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Não informado' : date.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

function firstName(name: string): string {
  return name.split(/\s+/)[0] || 'motorista'
}
