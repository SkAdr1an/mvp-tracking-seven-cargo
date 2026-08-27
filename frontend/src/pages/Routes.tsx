import { AlertTriangle, ArrowRight, Calculator, Clock3, Gauge, Info, MapPin, Pause, Play, Plus, RotateCcw, Route as RouteIcon, ShieldAlert, Timer, Trash2, Waypoints } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet'
import { Dispatch, FormEvent, SetStateAction, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { RoutePreview, RouteRiskFactor, RouteWaypoint, TrafficRoute } from '../types'
import { formatDuration } from '../utils'
import { MapResizeController } from '../components/MapResizeController'
import { calculateCommercial, commercialBaseFor, type CommercialValues, type TollResponsibility } from '../routeCommercial'
import '../route-commercial.css'

const DEFAULT_MIN_SPEED = 50
const DEFAULT_MAX_SPEED = 60
const INITIAL_COMMERCIAL_BASE = commercialBaseFor('betim-jaboatao')!

export function Routes() {
  const [origin, setOrigin] = useState('Betim, MG, Brasil')
  const [destination, setDestination] = useState('Jaboatão dos Guararapes, PE, Brasil')
  const [waypoints, setWaypoints] = useState<string[]>([])
  const [routeProfile, setRouteProfile] = useState('trafegus_betim_jaboatao')
  const [selectedRouteId, setSelectedRouteId] = useState('betim-jaboatao')
  const catalog = useQuery({ queryKey: ['route-catalog'], queryFn: api.trafficIncidents, staleTime: 300_000 })
  const [minSpeed, setMinSpeed] = useState(DEFAULT_MIN_SPEED)
  const [maxSpeed, setMaxSpeed] = useState(DEFAULT_MAX_SPEED)
  const [distanceOverride, setDistanceOverride] = useState('')
  const [stopMinutes, setStopMinutes] = useState(0)
  const [marginPercent, setMarginPercent] = useState(10)
  const [simulationProgress, setSimulationProgress] = useState(0)
  const [simulationSpeed, setSimulationSpeed] = useState(5)
  const [simulationRunning, setSimulationRunning] = useState(false)
  const [grossPayment, setGrossPayment] = useState<number|null>(INITIAL_COMMERCIAL_BASE.grossPayment)
  const [driverPayment, setDriverPayment] = useState<number|null>(INITIAL_COMMERCIAL_BASE.driverPayment)
  const [tolls, setTolls] = useState<number|null>(INITIAL_COMMERCIAL_BASE.toll)
  const [partnerFuelReference, setPartnerFuelReference] = useState<number|null>(INITIAL_COMMERCIAL_BASE.partnerFuelReference)
  const [directExtras, setDirectExtras] = useState<number|null>(0)
  const [tollResponsibility, setTollResponsibility] = useState<TollResponsibility>(INITIAL_COMMERCIAL_BASE.tollResponsibility)
  const [costBaseSaved, setCostBaseSaved] = useState(false)
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
  useEffect(() => {
    if (!simulationRunning) return
    const timer = window.setInterval(() => setSimulationProgress((current) => {
      const next = Math.min(100, current + simulationSpeed * .25)
      if (next >= 100) setSimulationRunning(false)
      return next
    }), 500)
    return () => window.clearInterval(timer)
  }, [simulationRunning, simulationSpeed])
  const addWaypoint = () => setWaypoints((current) => [...current, ''])
  const originSuggestions = [...new Set(catalog.data?.routes.map((route) => route.origin_name) ?? [])]
  const destinationSuggestions = [...new Set(catalog.data?.routes.map((route) => route.destination_name) ?? [])]
  const waypointSuggestions = [...new Set([...originSuggestions, ...destinationSuggestions])]
  const selectedCatalogRoute = catalog.data?.routes.find((route) => route.id === selectedRouteId)
  const selectCatalogRoute = (routeId: string) => {
    setSelectedRouteId(routeId)
    const route = catalog.data?.routes.find((item) => item.id === routeId)
    if (!route) {
      setRouteProfile('')
      return
    }
    setOrigin(route.origin_name)
    setDestination(route.destination_name)
    setWaypoints([])
    setDistanceOverride('')
    setSimulationProgress(0)
    setSimulationRunning(false)
    setRouteProfile(route.id === 'betim-jaboatao' ? 'trafegus_betim_jaboatao' : '')
    const defaults = commercialBaseFor(route.id, route.name)
    const saved = readCostBase(route.id)
    setGrossPayment(saved?.grossPayment ?? defaults?.grossPayment ?? null)
    setDriverPayment(saved?.driverPayment ?? defaults?.driverPayment ?? null)
    setTolls(saved?.toll ?? defaults?.toll ?? null)
    setPartnerFuelReference(saved?.partnerFuelReference ?? defaults?.partnerFuelReference ?? null)
    setDirectExtras(saved?.directExtras ?? 0)
    setTollResponsibility(saved?.tollResponsibility ?? defaults?.tollResponsibility ?? 'TO_VALIDATE')
    setCostBaseSaved(false)
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const request = { origin, destination, departure_at: new Date(departure).toISOString(), operational_speed_min_kmh: minSpeed, operational_speed_max_kmh: maxSpeed, waypoints: waypoints.map((point) => point.trim()).filter(Boolean), route_profile: routeProfile || undefined }
    lastRequest.current = request
    preview.mutate(request)
  }
  const catalogDistance = selectedCatalogRoute ? routeDistanceKm(selectedCatalogRoute) : 0
  const simulatedDistance = Math.max(0, Number(distanceOverride) || catalogDistance)
  const averageSpeed = Math.max(1, (minSpeed + maxSpeed) / 2)
  const drivingMinutes = simulatedDistance / averageSpeed * 60
  const subtotalMinutes = drivingMinutes + stopMinutes
  const marginMinutes = subtotalMinutes * marginPercent / 100
  const totalMinutes = subtotalMinutes + marginMinutes
  const simulatedArrival = new Date(new Date(departure).getTime() + totalMinutes * 60_000)
  const commercialValues: CommercialValues = {grossPayment,driverPayment,toll:tolls,partnerFuelReference,directExtras,tollResponsibility}
  const commercialResult = calculateCommercial(commercialValues)
  const setDepartureNow = () => {
    const date = new Date()
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
    setDeparture(date.toISOString().slice(0,16))
  }
  const saveCostBase = () => {
    if (!selectedRouteId) return
    localStorage.setItem(`seven:route-cost:${selectedRouteId}`,JSON.stringify(commercialValues))
    setCostBaseSaved(true)
  }

  return <div className="route-layout">
    <section className="panel route-form">
      <span className="eyebrow">Simulação operacional</span><h2>Planeje a rota do caminhão</h2>
      <p>A estimativa combina a rota viária com a faixa de velocidade praticada pela operação. Adicione todos os pontos pelos quais o veículo deve passar.</p>
      <form onSubmit={submit}>
        <label><span>Corredor operacional</span><div className="route-profile"><RouteIcon size={17} /><select value={selectedRouteId} onChange={(event) => selectCatalogRoute(event.target.value)}><option value="">Rota livre · definir manualmente</option>{catalog.data?.routes.map((route: TrafficRoute) => <option key={route.id} value={route.id}>{route.name}</option>)}</select></div>{catalog.isLoading && <small className="profile-note">Carregando rotas operacionais…</small>}{catalog.isError && <small className="profile-note profile-note--error">Não foi possível carregar o catálogo. A rota livre permanece disponível.</small>}{routeProfile && <small className="profile-note">Usa 21 pontos de controle amostrados da geometria Trafegus; a via entre eles é recalculada pela TomTom.</small>}{selectedRouteId && !routeProfile && <small className="profile-note">Origem e destino preenchidos pelo catálogo oficial da operação.</small>}</label>
        <LocationField label="Origem" value={origin} onChange={setOrigin} suggestions={originSuggestions} listId="route-origins" />
        <div className="route-line" />
        {waypoints.map((waypoint, index) => <div className="waypoint-input" key={index}><LocationField label={`Ponto obrigatório ${index + 1}`} value={waypoint} onChange={(value) => setWaypoints((current) => current.map((item, itemIndex) => itemIndex === index ? value : item))} suggestions={waypointSuggestions} listId={`route-waypoints-${index}`} /><button type="button" title="Remover ponto" onClick={() => setWaypoints((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={15} /></button></div>)}
        <button className="add-waypoint" type="button" onClick={addWaypoint}><Plus size={15} />Adicionar ponto obrigatório</button>
        <LocationField label="Destino" value={destination} onChange={setDestination} destination suggestions={destinationSuggestions} listId="route-destinations" />
        <label><span>Data e hora de saída</span><div className="departure-row"><div className="field"><Clock3 size={18} /><input type="datetime-local" required value={departure} onChange={(e) => setDeparture(e.target.value)} /></div><button type="button" onClick={setDepartureNow}>Iniciar agora</button></div></label>
        <div className="speed-range"><div className="speed-range__title"><span><Gauge size={16} />Velocidade operacional</span><strong>{minSpeed}–{maxSpeed} km/h</strong></div><p>Faixa média adotada pela operação, diferente do limite máximo da rodovia.</p><div><label><span>Mínima</span><input type="number" min="20" max="100" step="5" value={minSpeed} onChange={(e) => setMinSpeed(Number(e.target.value))} /></label><label><span>Máxima</span><input type="number" min="20" max="100" step="5" value={maxSpeed} onChange={(e) => setMaxSpeed(Number(e.target.value))} /></label></div></div>
        <section className="trip-simulator"><div className="trip-simulator__head"><div><span className="eyebrow">Seção operacional</span><h3>Tempo e duração da viagem</h3></div>{distanceOverride&&<button type="button" onClick={()=>setDistanceOverride('')}><RotateCcw/>Restaurar</button>}</div><div className="trip-simulator__fields"><label><span>Quilometragem</span><input type="number" min="1" step=".1" value={distanceOverride||catalogDistance.toFixed(1)} onChange={e=>setDistanceOverride(e.target.value)}/><small>{distanceOverride?'Ajuste manual':'Geometria salva'} · km</small></label><label><span>Paradas</span><input type="number" min="0" step="15" value={stopMinutes} onChange={e=>setStopMinutes(Math.max(0,Number(e.target.value)))}/><small>minutos</small></label><label><span>Folga operacional (%)</span><input type="number" min="0" max="100" step="1" value={marginPercent} onChange={e=>setMarginPercent(Math.max(0,Number(e.target.value)))}/><small className="folga-help">Percentual adicional aplicado ao tempo estimado para absorver variações da operação.</small></label></div><div className="trip-simulator__summary"><div><span>Tempo em movimento</span><strong>{formatDuration(drivingMinutes)}</strong></div><div><span>Duração prevista</span><strong>{formatDuration(totalMinutes)}</strong></div><div><span>Chegada prevista</span><strong>{Number.isFinite(simulatedArrival.getTime())?simulatedArrival.toLocaleString('pt-BR'):'—'}</strong></div></div></section>
        <CostCalculator values={commercialValues} setters={{setGrossPayment,setDriverPayment,setTolls,setPartnerFuelReference,setDirectExtras,setTollResponsibility}} result={commercialResult} routeBase={commercialBaseFor(selectedCatalogRoute?.id,selectedCatalogRoute?.name)} routeName={selectedCatalogRoute?.name} onSave={saveCostBase} saved={costBaseSaved} />
        {minSpeed >= maxSpeed && <div className="form-error">A velocidade mínima deve ser menor que a máxima.</div>}
        {preview.error && <div className="form-error">{preview.error.message}</div>}
        <div className="route-primary-actions"><button type="button" className="secondary-button simulation-button" disabled={!selectedCatalogRoute} onClick={()=>{if(simulationProgress>=100)setSimulationProgress(0);setSimulationRunning(value=>!value)}}>{simulationRunning?<><Pause/>Pausar</>:<><Play/>{simulationProgress>0?'Continuar':'Iniciar simulação'}</>}</button><button className="primary-button" disabled={preview.isPending || minSpeed >= maxSpeed}>{preview.isPending ? 'Analisando trechos...' : 'Calcular rota operacional'}<ArrowRight size={18} /></button></div>
      </form>
    </section>
    <RouteResult route={preview.data} catalogRoute={selectedCatalogRoute} requestedWaypoints={waypoints.filter(Boolean)} requestedSpeed={[minSpeed, maxSpeed]} simulation={{progress:simulationProgress,speed:simulationSpeed,running:simulationRunning,totalMinutes,departure,distance:simulatedDistance,onSpeed:setSimulationSpeed,onReset:()=>{setSimulationProgress(0);setSimulationRunning(false)}}} />
  </div>
}

interface CommercialSetters {
  setGrossPayment: Dispatch<SetStateAction<number|null>>
  setDriverPayment: Dispatch<SetStateAction<number|null>>
  setTolls: Dispatch<SetStateAction<number|null>>
  setPartnerFuelReference: Dispatch<SetStateAction<number|null>>
  setDirectExtras: Dispatch<SetStateAction<number|null>>
  setTollResponsibility: Dispatch<SetStateAction<TollResponsibility>>
}

function CostCalculator({values,setters,result,routeBase,routeName,onSave,saved}:{values:CommercialValues;setters:CommercialSetters;result:ReturnType<typeof calculateCommercial>;routeBase:ReturnType<typeof commercialBaseFor>;routeName?:string;onSave:()=>void;saved:boolean}) {
  const field=(label:string,value:number|null,setter:Dispatch<SetStateAction<number|null>>,help:string)=> <label className="commercial-field"><span>{label}</span><div className="commercial-input"><input type="number" min="0" step=".01" value={value??''} placeholder="A validar" onChange={event=>setter(event.target.value===''?null:Math.max(0,Number(event.target.value)))}/><small>R$</small></div><small>{help}</small></label>
  return <section className="cost-calculator">
    <div className="cost-calculator__head"><div><span className="eyebrow">Análise para negociação</span><h3><Calculator/>Resultado comercial da Seven</h3><small>{routeName||'Rota livre'} · valores editáveis e sem custos presumidos</small></div></div>
    {routeBase?.grossReference&&<div className="commercial-reference">Pagamento bruto informado como faixa: {money(routeBase.grossReference[0])} a {money(routeBase.grossReference[1])}. Defina o valor efetivamente negociado para calcular a margem.</div>}
    <div className="commercial-fields">
      {field('Pagamento bruto',values.grossPayment,setters.setGrossPayment,'Valor recebido pela Seven do cliente.')}
      {field('Pagamento ao motorista',values.driverPayment,setters.setDriverPayment,'Valor total negociado com o motorista ou transportador parceiro.')}
      {field('Pedágio',values.toll,setters.setTolls,'Valor estimado ou validado da rota.')}
      {field('Combustível estimado',values.partnerFuelReference,setters.setPartnerFuelReference,'Referência econômica do parceiro; não é custo da Seven.')}
      {field('Bônus/adicionais',values.directExtras,setters.setDirectExtras,'Outros custos diretos assumidos pela Seven. Opcional.')}
      <label className="commercial-field"><span>Responsabilidade do pedágio</span><select value={values.tollResponsibility} onChange={event=>setters.setTollResponsibility(event.target.value as TollResponsibility)}><option value="TO_VALIDATE">A validar</option><option value="SEVEN">Seven Cargo</option><option value="PARTNER">Motorista/parceiro</option></select><small>Define em qual referência o pedágio será descontado.</small></label>
    </div>
    <div className="commercial-results"><div className={result.grossResult==null?'':result.grossResult>=0?'positive':'negative'}><span>Resultado bruto Seven</span><strong>{optionalMoney(result.grossResult)}</strong><small>Bruto − motorista − pedágio Seven − adicionais.</small></div><div><span>Margem comercial Seven</span><strong>{result.commercialMargin==null?'A validar':`${result.commercialMargin.toFixed(1)}%`}</strong><small>Resultado bruto / pagamento bruto.</small></div><div><span>Referência econômica do parceiro</span><strong>{optionalMoney(result.partnerEconomicReference)}</strong><small>Motorista − combustível − pedágio do parceiro.</small></div></div>
    {values.tollResponsibility==='TO_VALIDATE'&&<p className="commercial-warning">Confirme quem assume o pedágio antes de considerar os resultados definitivos.</p>}
    <button type="button" className="save-cost-base" disabled={!routeName} onClick={onSave}>{saved?'Base salva para esta rota':'Salvar como base desta rota'}</button>
    <p className="cost-disclaimer">Combustível é exibido somente como referência do parceiro. Confirme valores, responsabilidade do pedágio e custos diretos antes de fechar a negociação.</p>
  </section>
}

function LocationField({ label, value, onChange, destination = false, suggestions = [], listId }: { label: string; value: string; onChange: (value: string) => void; destination?: boolean; suggestions?: string[]; listId?: string }) {
  return <label><span>{label}</span><div className={`field${destination ? ' field--destination' : ''}`}><MapPin size={18} /><input required list={listId} value={value} onChange={(event) => onChange(event.target.value)} placeholder="Cidade, endereço ou coordenadas" />{listId && <datalist id={listId}>{suggestions.map((suggestion) => <option value={suggestion} key={suggestion} />)}</datalist>}</div>{suggestions.length > 0 && <small className="location-suggestion-note">{suggestions.length} locais operacionais disponíveis · digite para pesquisar</small>}</label>
}

interface SimulationState {progress:number;speed:number;running:boolean;totalMinutes:number;departure:string;distance:number;onSpeed:(speed:number)=>void;onReset:()=>void}
function RouteResult({ route, catalogRoute, requestedWaypoints, requestedSpeed, simulation }: { route?: RoutePreview; catalogRoute?: TrafficRoute; requestedWaypoints: string[]; requestedSpeed: [number, number]; simulation:SimulationState }) {
  if (!route) return <section className="panel route-result route-result--map">{catalogRoute ? <><PlannerRouteMap route={catalogRoute} simulation={simulation} /><div className="planner-map-caption"><span className="eyebrow">{simulation.progress>0?'Simulação operacional':'Geometria operacional salva'}</span><h2>{catalogRoute.name}</h2><p>{simulation.progress>0?`${simulation.progress.toFixed(0)}% concluído · ${(simulation.distance*(1-simulation.progress/100)).toFixed(1)} km restantes`:'O mapa permanece disponível mesmo quando o provedor de cálculo estiver indisponível.'}</p></div><SimulationControls simulation={simulation}/></> : <div className="result-empty"><div><RouteIcon size={34} /></div><h2>Selecione uma rota</h2><p>Escolha um corredor operacional para visualizar sua geometria no mapa.</p></div>}</section>
  const operationalMinutes = route.operational_duration_minutes ?? Math.max(route.duration_with_traffic_minutes, route.distance_km / ((requestedSpeed[0] + requestedSpeed[1]) / 2) * 60)
  const operationalArrival = route.operational_arrival_at ?? new Date(new Date(route.departure_at).getTime() + operationalMinutes * 60000).toISOString()
  const routeWaypoints: RouteWaypoint[] = route.waypoints?.length ? route.waypoints : requestedWaypoints.map((address, index) => ({ address, sequence: index + 1 }))
  const risks = route.risk_factors ?? []
  return <section className="panel route-result">
    <div className="route-result__header"><div><span className="eyebrow">Resultado · atualização automática a cada 3 min</span><h2>{route.origin.address} <ArrowRight size={18} /> {route.destination.address}</h2></div><em className={`route-status route-status--${route.status}`}>{route.status === 'normal' ? 'Fluxo normal' : route.status === 'attention' ? 'Atenção' : 'Crítico'}</em></div>
    {catalogRoute && <><PlannerRouteMap route={catalogRoute} compact simulation={simulation}/><SimulationControls simulation={simulation}/></>}
    <div className="route-metrics"><ResultMetric icon={RouteIcon} label="Distância" value={`${route.distance_km.toLocaleString('pt-BR')} km`} /><ResultMetric icon={Gauge} label="Faixa operacional" value={`${route.operational_speed_min_kmh ?? requestedSpeed[0]}–${route.operational_speed_max_kmh ?? requestedSpeed[1]} km/h`} /><ResultMetric icon={Timer} label="Tempo operacional" value={formatDuration(operationalMinutes)} /><ResultMetric icon={Clock3} label="Chegada operacional" value={formatDate(operationalArrival)} /></div>
    <div className="estimate-breakdown"><h3>Como chegamos à estimativa</h3><div><EstimateStep label="Roteador para caminhão" value={formatDuration(route.duration_without_traffic_minutes)} /><ArrowRight size={14} /><EstimateStep label="Trânsito previsto" value={`+ ${formatDuration(route.traffic_delay_minutes)}`} /><ArrowRight size={14} /><EstimateStep label="Operação 50–60 km/h" value={formatDuration(operationalMinutes)} emphasis /></div><p>O tempo operacional nunca fica abaixo da previsão do provedor. Paradas, jornada legal e tempo de carga/descarga só entram quando informados pelo backend.</p></div>
    {routeWaypoints.length > 0 && <section className="route-section"><div className="route-section__title"><Waypoints size={18} /><div><h3>Pontos obrigatórios</h3><p>A sequência abaixo deve fazer parte da geometria calculada.</p></div></div><ol className="waypoint-list">{routeWaypoints.map((point, index) => <li key={`${point.address}-${index}`}><i>{point.sequence ?? index + 1}</i><div><strong>{point.name || point.address || `Ponto ${index + 1}`}</strong>{point.estimated_arrival_at && <span>Passagem estimada: {formatDate(point.estimated_arrival_at)}</span>}</div></li>)}</ol></section>}
    <section className="route-section"><div className="route-section__title"><ShieldAlert size={18} /><div><h3>Fatores de risco</h3><p>Ocorrências conhecidas no momento da consulta.</p></div></div>{risks.length ? <div className="risk-list">{risks.map((risk, index) => <RiskItem risk={risk} key={`${risk.type}-${index}`} />)}</div> : <div className="no-risk"><Info size={17} /><span>Nenhum fator foi retornado pelas fontes disponíveis. Isso não confirma ausência de acidentes, fiscalização ou retenções futuras.</span></div>}</section>
    {route.timeline && route.timeline.length > 0 && <section className="route-section"><div className="route-section__title"><Clock3 size={18} /><div><h3>Linha do tempo</h3><p>Passagens e interferências previstas ao longo da viagem.</p></div></div><div className="route-timeline">{route.timeline.map((item, index) => <div key={index}><i /><span>{item.estimated_arrival_at ? formatDate(item.estimated_arrival_at) : item.distance_from_origin_km != null ? `${item.distance_from_origin_km} km` : `Etapa ${index + 1}`}</span><strong>{item.title || item.type || 'Trecho da rota'}</strong>{item.description && <p>{item.description}</p>}</div>)}</div></section>}
    <div className="traffic-comparison"><div><span>Fluxo livre</span><strong>{formatDuration(route.duration_without_traffic_minutes)}</strong></div><div className="comparison-line"><i style={{ width: `${Math.max(10, Math.min(100, route.duration_without_traffic_minutes / operationalMinutes * 100))}%` }} /></div><div><span>Previsão operacional</span><strong>{formatDuration(operationalMinutes)}</strong></div></div>
    <div className="traffic-note"><Info size={16} /><span>{trafficExplanation(route)}</span></div>
  </section>
}

function PlannerRouteMap({ route, compact = false, simulation }: { route: TrafficRoute; compact?: boolean; simulation:SimulationState }) {
  const points = route.geometry.map((point) => [point.latitude, point.longitude] as [number, number])
  const visiblePoints = points.length ? points : [[route.origin_latitude, route.origin_longitude], [route.destination_latitude, route.destination_longitude]] as [number, number][]
  const currentIndex=Math.min(visiblePoints.length-1,Math.floor((visiblePoints.length-1)*simulation.progress/100))
  const travelled=visiblePoints.slice(0,currentIndex+1)
  const currentPoint=visiblePoints[currentIndex]
  return <div className={`planner-route-map${compact ? ' planner-route-map--compact' : ''}`}><MapContainer center={visiblePoints[0]} zoom={6} zoomControl className="map"><MapResizeController points={visiblePoints} command={{ id: route.id.split('').reduce((value,letter)=>value+letter.charCodeAt(0),1), mode:'fit' }} /><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />{visiblePoints.length > 1 && <Polyline positions={visiblePoints} pathOptions={{ color:'#d3a91d', weight:5, opacity:.62 }}><Tooltip sticky>{route.name}</Tooltip></Polyline>}{travelled.length>1&&<Polyline positions={travelled} pathOptions={{color:'#38d996',weight:6,opacity:1}}/>}<CircleMarker center={[route.origin_latitude,route.origin_longitude]} radius={8} pathOptions={{color:'#fff',weight:2,fillColor:'#38d996',fillOpacity:1}}><Tooltip direction="top">Origem · {route.origin_name}</Tooltip></CircleMarker><CircleMarker center={[route.destination_latitude,route.destination_longitude]} radius={8} pathOptions={{color:'#fff',weight:2,fillColor:'#ef6a5b',fillOpacity:1}}><Tooltip direction="top">Destino · {route.destination_name}</Tooltip></CircleMarker>{simulation.progress>0&&<CircleMarker center={currentPoint} radius={10} pathOptions={{color:'#fff',weight:3,fillColor:'#f3c623',fillOpacity:1}}><Tooltip permanent direction="top">{simulation.progress.toFixed(0)}%</Tooltip></CircleMarker>}</MapContainer><div className="planner-map-legend"><span><i className="dot dot--green"/>Percorrido</span><span><i className="dot dot--red"/>Destino</span><span className="legend-route">Rota planejada</span></div></div>
}

function SimulationControls({simulation}:{simulation:SimulationState}){const simulatedTime=new Date(new Date(simulation.departure).getTime()+simulation.totalMinutes*60_000*simulation.progress/100);return <div className="simulation-controls"><div><span>Progresso</span><strong>{simulation.progress.toFixed(0)}%</strong></div><progress max="100" value={simulation.progress}/><div className="simulation-clock"><span>Horário simulado</span><strong>{Number.isFinite(simulatedTime.getTime())?simulatedTime.toLocaleString('pt-BR'):'—'}</strong></div><div className="simulation-speeds">{[1,5,20].map(speed=><button type="button" className={simulation.speed===speed?'active':''} onClick={()=>simulation.onSpeed(speed)} key={speed}>{speed}x</button>)}</div><button type="button" className="simulation-reset" onClick={simulation.onReset}><RotateCcw/>Reiniciar</button></div>}

function routeDistanceKm(route:TrafficRoute):number{if(route.distance_m&&route.distance_m>0)return route.distance_m/1000;let total=0;for(let index=1;index<route.geometry.length;index++){const first=route.geometry[index-1],second=route.geometry[index];const toRad=(value:number)=>value*Math.PI/180;const lat=toRad(second.latitude-first.latitude);const lon=toRad(second.longitude-first.longitude);const a=Math.sin(lat/2)**2+Math.cos(toRad(first.latitude))*Math.cos(toRad(second.latitude))*Math.sin(lon/2)**2;total+=6371*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a))}return total}
function EstimateStep({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) { return <div className={emphasis ? 'estimate-step estimate-step--emphasis' : 'estimate-step'}><span>{label}</span><strong>{value}</strong></div> }
function RiskItem({ risk }: { risk: RouteRiskFactor }) { return <article className={`risk-item risk-item--${risk.severity || 'medium'}`}><AlertTriangle size={17} /><div><strong>{risk.title || risk.type || 'Risco operacional'}</strong><p>{risk.description || 'Sem detalhes adicionais.'}</p><small>{[risk.source, risk.updated_at ? `Atualizado ${formatDate(risk.updated_at)}` : null, risk.delay_minutes ? `+${formatDuration(risk.delay_minutes)}` : null].filter(Boolean).join(' · ')}</small></div></article> }
function formatDate(value: string): string { return new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) }
function money(value:number):string{return new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number.isFinite(value)?value:0)}
function optionalMoney(value:number|null):string{return value==null?'A validar':money(value)}
function readCostBase(routeId:string):Partial<CommercialValues>|null{try{const value=localStorage.getItem(`seven:route-cost:${routeId}`);if(!value)return null;const parsed=JSON.parse(value);return 'grossPayment' in parsed?parsed:null}catch{return null}}
function trafficExplanation(route: RoutePreview): string { if (route.traffic_delay_minutes === 0) return 'O provedor não mediu acréscimo de trânsito neste instante. A previsão operacional ainda considera a velocidade média do caminhão e não garante pista livre em todos os trechos.'; const live = route.live_traffic_delay_minutes > 0 ? ` Deste total, ${formatDuration(route.live_traffic_delay_minutes)} são de trânsito ao vivo em ${route.traffic_length_km.toLocaleString('pt-BR')} km monitorados.` : ' A diferença disponível é uma previsão histórica; não há atraso ao vivo retornado.'; return `${formatDuration(route.traffic_delay_minutes)} de acréscimo em relação ao fluxo livre.${live}` }
function ResultMetric({ icon: Icon, label, value }: { icon: typeof RouteIcon; label: string; value: string }) { return <div><i><Icon size={20} /></i><span>{label}</span><strong>{value}</strong></div> }
