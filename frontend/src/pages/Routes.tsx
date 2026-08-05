import { AlertTriangle, ArrowRight, Clock3, Gauge, Info, MapPin, Plus, Route as RouteIcon, ShieldAlert, Timer, Trash2, Waypoints } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { FormEvent, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { RoutePreview, RouteRiskFactor, RouteWaypoint } from '../types'
import { formatDuration } from '../utils'

const DEFAULT_MIN_SPEED = 50
const DEFAULT_MAX_SPEED = 60

export function Routes() {
  const [origin, setOrigin] = useState('Betim, MG, Brasil')
  const [destination, setDestination] = useState('Jaboatão dos Guararapes, PE, Brasil')
  const [waypoints, setWaypoints] = useState<string[]>([])
  const [routeProfile, setRouteProfile] = useState('trafegus_betim_jaboatao')
  const [minSpeed, setMinSpeed] = useState(DEFAULT_MIN_SPEED)
  const [maxSpeed, setMaxSpeed] = useState(DEFAULT_MAX_SPEED)
  const [departure, setDeparture] = useState(() => {
    const date = new Date(Date.now() + 3600000)
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
    return date.toISOString().slice(0, 16)
  })
  const preview = useMutation({ mutationFn: api.routePreview })
  const lastRequest = useRef<Parameters<typeof api.routePreview>[0] | null>(null)
  const refreshRoute = preview.mutate
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (lastRequest.current) refreshRoute(lastRequest.current)
    }, 180_000)
    return () => window.clearInterval(timer)
  }, [refreshRoute])
  const addWaypoint = () => setWaypoints((current) => [...current, ''])
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const request = { origin, destination, departure_at: new Date(departure).toISOString(), operational_speed_min_kmh: minSpeed, operational_speed_max_kmh: maxSpeed, waypoints: waypoints.map((point) => point.trim()).filter(Boolean), route_profile: routeProfile || undefined }
    lastRequest.current = request
    preview.mutate(request)
  }

  return <div className="route-layout">
    <section className="panel route-form">
      <span className="eyebrow">Simulação operacional</span><h2>Planeje a rota do caminhão</h2>
      <p>A estimativa combina a rota viária com a faixa de velocidade praticada pela operação. Adicione todos os pontos pelos quais o veículo deve passar.</p>
      <form onSubmit={submit}>
        <label><span>Corredor operacional</span><div className="route-profile"><RouteIcon size={17} /><select value={routeProfile} onChange={(event) => setRouteProfile(event.target.value)}><option value="trafegus_betim_jaboatao">Rota Trafegus · Betim → Jaboatão</option><option value="">Rota livre · definir manualmente</option></select></div>{routeProfile && <small className="profile-note">Usa 21 pontos de controle amostrados da geometria Trafegus; a via entre eles é recalculada pela TomTom.</small>}</label>
        <LocationField label="Origem" value={origin} onChange={setOrigin} />
        <div className="route-line" />
        {waypoints.map((waypoint, index) => <div className="waypoint-input" key={index}><LocationField label={`Ponto obrigatório ${index + 1}`} value={waypoint} onChange={(value) => setWaypoints((current) => current.map((item, itemIndex) => itemIndex === index ? value : item))} /><button type="button" title="Remover ponto" onClick={() => setWaypoints((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={15} /></button></div>)}
        <button className="add-waypoint" type="button" onClick={addWaypoint}><Plus size={15} />Adicionar ponto obrigatório</button>
        <LocationField label="Destino" value={destination} onChange={setDestination} destination />
        <div className="speed-range"><div className="speed-range__title"><span><Gauge size={16} />Velocidade operacional</span><strong>{minSpeed}–{maxSpeed} km/h</strong></div><p>Faixa média adotada pela Seven Cargo, diferente do limite máximo da rodovia.</p><div><label><span>Mínima</span><input type="number" min="20" max="100" value={minSpeed} onChange={(e) => setMinSpeed(Number(e.target.value))} /></label><label><span>Máxima</span><input type="number" min="20" max="100" value={maxSpeed} onChange={(e) => setMaxSpeed(Number(e.target.value))} /></label></div></div>
        <label><span>Data e hora de saída</span><div className="field"><Clock3 size={18} /><input type="datetime-local" required value={departure} onChange={(e) => setDeparture(e.target.value)} /></div></label>
        {minSpeed > maxSpeed && <div className="form-error">A velocidade mínima não pode ser maior que a máxima.</div>}
        {preview.error && <div className="form-error">{preview.error.message}</div>}
        <button className="primary-button" disabled={preview.isPending || minSpeed > maxSpeed}>{preview.isPending ? 'Analisando trechos...' : 'Calcular rota operacional'}<ArrowRight size={18} /></button>
      </form>
    </section>
    <RouteResult route={preview.data} requestedWaypoints={waypoints.filter(Boolean)} requestedSpeed={[minSpeed, maxSpeed]} />
  </div>
}

function LocationField({ label, value, onChange, destination = false }: { label: string; value: string; onChange: (value: string) => void; destination?: boolean }) {
  return <label><span>{label}</span><div className={`field${destination ? ' field--destination' : ''}`}><MapPin size={18} /><input required value={value} onChange={(event) => onChange(event.target.value)} placeholder="Cidade, endereço ou coordenadas" /></div></label>
}

function RouteResult({ route, requestedWaypoints, requestedSpeed }: { route?: RoutePreview; requestedWaypoints: string[]; requestedSpeed: [number, number] }) {
  if (!route) return <section className="panel route-result"><div className="result-empty"><div><RouteIcon size={34} /></div><h2>Sua análise aparecerá aqui</h2><p>O resultado separa o tempo informado pelo provedor da previsão operacional do caminhão e explicita os riscos conhecidos.</p></div></section>
  const operationalMinutes = route.operational_duration_minutes ?? Math.max(route.duration_with_traffic_minutes, route.distance_km / ((requestedSpeed[0] + requestedSpeed[1]) / 2) * 60)
  const operationalArrival = route.operational_arrival_at ?? new Date(new Date(route.departure_at).getTime() + operationalMinutes * 60000).toISOString()
  const routeWaypoints: RouteWaypoint[] = route.waypoints?.length ? route.waypoints : requestedWaypoints.map((address, index) => ({ address, sequence: index + 1 }))
  const risks = route.risk_factors ?? []
  return <section className="panel route-result">
    <div className="route-result__header"><div><span className="eyebrow">Resultado · atualização automática a cada 3 min</span><h2>{route.origin.address} <ArrowRight size={18} /> {route.destination.address}</h2></div><em className={`route-status route-status--${route.status}`}>{route.status === 'normal' ? 'Fluxo normal' : route.status === 'attention' ? 'Atenção' : 'Crítico'}</em></div>
    <div className="route-metrics"><ResultMetric icon={RouteIcon} label="Distância" value={`${route.distance_km.toLocaleString('pt-BR')} km`} /><ResultMetric icon={Gauge} label="Faixa operacional" value={`${route.operational_speed_min_kmh ?? requestedSpeed[0]}–${route.operational_speed_max_kmh ?? requestedSpeed[1]} km/h`} /><ResultMetric icon={Timer} label="Tempo operacional" value={formatDuration(operationalMinutes)} /><ResultMetric icon={Clock3} label="Chegada operacional" value={formatDate(operationalArrival)} /></div>
    <div className="estimate-breakdown"><h3>Como chegamos à estimativa</h3><div><EstimateStep label="Roteador para caminhão" value={formatDuration(route.duration_without_traffic_minutes)} /><ArrowRight size={14} /><EstimateStep label="Trânsito previsto" value={`+ ${formatDuration(route.traffic_delay_minutes)}`} /><ArrowRight size={14} /><EstimateStep label="Operação 50–60 km/h" value={formatDuration(operationalMinutes)} emphasis /></div><p>O tempo operacional nunca fica abaixo da previsão do provedor. Paradas, jornada legal e tempo de carga/descarga só entram quando informados pelo backend.</p></div>
    {routeWaypoints.length > 0 && <section className="route-section"><div className="route-section__title"><Waypoints size={18} /><div><h3>Pontos obrigatórios</h3><p>A sequência abaixo deve fazer parte da geometria calculada.</p></div></div><ol className="waypoint-list">{routeWaypoints.map((point, index) => <li key={`${point.address}-${index}`}><i>{point.sequence ?? index + 1}</i><div><strong>{point.name || point.address || `Ponto ${index + 1}`}</strong>{point.estimated_arrival_at && <span>Passagem estimada: {formatDate(point.estimated_arrival_at)}</span>}</div></li>)}</ol></section>}
    <section className="route-section"><div className="route-section__title"><ShieldAlert size={18} /><div><h3>Fatores de risco</h3><p>Ocorrências conhecidas no momento da consulta.</p></div></div>{risks.length ? <div className="risk-list">{risks.map((risk, index) => <RiskItem risk={risk} key={`${risk.type}-${index}`} />)}</div> : <div className="no-risk"><Info size={17} /><span>Nenhum fator foi retornado pelas fontes disponíveis. Isso não confirma ausência de acidentes, fiscalização ou retenções futuras.</span></div>}</section>
    {route.timeline && route.timeline.length > 0 && <section className="route-section"><div className="route-section__title"><Clock3 size={18} /><div><h3>Linha do tempo</h3><p>Passagens e interferências previstas ao longo da viagem.</p></div></div><div className="route-timeline">{route.timeline.map((item, index) => <div key={index}><i /><span>{item.estimated_arrival_at ? formatDate(item.estimated_arrival_at) : item.distance_from_origin_km != null ? `${item.distance_from_origin_km} km` : `Etapa ${index + 1}`}</span><strong>{item.title || item.type || 'Trecho da rota'}</strong>{item.description && <p>{item.description}</p>}</div>)}</div></section>}
    <div className="traffic-comparison"><div><span>Fluxo livre</span><strong>{formatDuration(route.duration_without_traffic_minutes)}</strong></div><div className="comparison-line"><i style={{ width: `${Math.max(10, Math.min(100, route.duration_without_traffic_minutes / operationalMinutes * 100))}%` }} /></div><div><span>Previsão operacional</span><strong>{formatDuration(operationalMinutes)}</strong></div></div>
    <div className="traffic-note"><Info size={16} /><span>{trafficExplanation(route)}</span></div>
  </section>
}

function EstimateStep({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) { return <div className={emphasis ? 'estimate-step estimate-step--emphasis' : 'estimate-step'}><span>{label}</span><strong>{value}</strong></div> }
function RiskItem({ risk }: { risk: RouteRiskFactor }) { return <article className={`risk-item risk-item--${risk.severity || 'medium'}`}><AlertTriangle size={17} /><div><strong>{risk.title || risk.type || 'Risco operacional'}</strong><p>{risk.description || 'Sem detalhes adicionais.'}</p><small>{[risk.source, risk.updated_at ? `Atualizado ${formatDate(risk.updated_at)}` : null, risk.delay_minutes ? `+${formatDuration(risk.delay_minutes)}` : null].filter(Boolean).join(' · ')}</small></div></article> }
function formatDate(value: string): string { return new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) }
function trafficExplanation(route: RoutePreview): string { if (route.traffic_delay_minutes === 0) return 'O provedor não mediu acréscimo de trânsito neste instante. A previsão operacional ainda considera a velocidade média do caminhão e não garante pista livre em todos os trechos.'; const live = route.live_traffic_delay_minutes > 0 ? ` Deste total, ${formatDuration(route.live_traffic_delay_minutes)} são de trânsito ao vivo em ${route.traffic_length_km.toLocaleString('pt-BR')} km monitorados.` : ' A diferença disponível é uma previsão histórica; não há atraso ao vivo retornado.'; return `${formatDuration(route.traffic_delay_minutes)} de acréscimo em relação ao fluxo livre.${live}` }
function ResultMetric({ icon: Icon, label, value }: { icon: typeof RouteIcon; label: string; value: string }) { return <div><i><Icon size={20} /></i><span>{label}</span><strong>{value}</strong></div> }
