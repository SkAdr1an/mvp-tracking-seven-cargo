import { AlertTriangle, ArrowRight, Calculator, Clock3, Fuel, Gauge, Info, MapPin, Pause, Play, Plus, RotateCcw, Route as RouteIcon, ShieldAlert, Timer, Trash2, TrendingUp, Wallet, Waypoints } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet'
import { Dispatch, FormEvent, SetStateAction, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { RoutePreview, RouteRiskFactor, RouteWaypoint, TrafficRoute } from '../types'
import { formatDuration } from '../utils'
import { MapResizeController } from '../components/MapResizeController'

const DEFAULT_MIN_SPEED = 50
const DEFAULT_MAX_SPEED = 60
const BETIM_JABOATAO_COST_BASE = { freightValue:16000, tolls:338.65, fuelBudget:4750, operatingCostOverride:18107.48 }

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
  const [dieselPrice, setDieselPrice] = useState(6.15)
  const [fuelConsumption, setFuelConsumption] = useState(2.5)
  const [tolls, setTolls] = useState(BETIM_JABOATAO_COST_BASE.tolls)
  const [fuelBudget, setFuelBudget] = useState(BETIM_JABOATAO_COST_BASE.fuelBudget)
  const [operatingCostOverride, setOperatingCostOverride] = useState(BETIM_JABOATAO_COST_BASE.operatingCostOverride)
  const [driverDaily, setDriverDaily] = useState(180)
  const [foodDaily, setFoodDaily] = useState(80)
  const [lodgingDaily, setLodgingDaily] = useState(0)
  const [loadingCosts, setLoadingCosts] = useState(0)
  const [otherCosts, setOtherCosts] = useState(0)
  const [commissionPercent, setCommissionPercent] = useState(0)
  const [contingencyPercent, setContingencyPercent] = useState(5)
  const [targetMarginPercent, setTargetMarginPercent] = useState(15)
  const [freightValue, setFreightValue] = useState(BETIM_JABOATAO_COST_BASE.freightValue)
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
    const defaults = route.id === 'betim-jaboatao' ? BETIM_JABOATAO_COST_BASE : {freightValue:0,tolls:0,fuelBudget:0,operatingCostOverride:0}
    const saved = readCostBase(route.id)
    setFreightValue(saved?.freightValue ?? defaults.freightValue)
    setTolls(saved?.tolls ?? defaults.tolls)
    setFuelBudget(saved?.fuelBudget ?? defaults.fuelBudget)
    setOperatingCostOverride(saved?.operatingCostOverride ?? defaults.operatingCostOverride)
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
  const driverDays = Math.max(1, Math.ceil(totalMinutes / 1440))
  const calculatedFuelCost = fuelConsumption > 0 ? simulatedDistance / fuelConsumption * dieselPrice : 0
  const fuelCost = fuelBudget > 0 ? fuelBudget : calculatedFuelCost
  const driverCost = driverDays * (driverDaily + foodDaily + lodgingDaily)
  const commissionCost = freightValue * commissionPercent / 100
  const baseCost = fuelCost + tolls + driverCost + loadingCosts + otherCosts
  const directCost = baseCost + commissionCost
  const contingencyCost = directCost * contingencyPercent / 100
  const calculatedTripCost = directCost + contingencyCost
  const totalTripCost = operatingCostOverride > 0 ? operatingCostOverride : calculatedTripCost
  const targetMargin = Math.min(95, Math.max(0, targetMarginPercent)) / 100
  const contingencyFactor = 1 + contingencyPercent / 100
  const commissionRate = commissionPercent / 100
  const minimumFreight = operatingCostOverride > 0 ? operatingCostOverride / Math.max(.05,1-targetMargin) : baseCost * contingencyFactor / Math.max(.05, 1 - targetMargin - commissionRate * contingencyFactor)
  const estimatedProfit = freightValue - totalTripCost
  const estimatedMargin = freightValue > 0 ? estimatedProfit / freightValue * 100 : 0
  const setDepartureNow = () => {
    const date = new Date()
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
    setDeparture(date.toISOString().slice(0,16))
  }
  const saveCostBase = () => {
    if (!selectedRouteId) return
    localStorage.setItem(`seven:route-cost:${selectedRouteId}`,JSON.stringify({freightValue,tolls,fuelBudget,operatingCostOverride}))
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
        <div className="speed-range"><div className="speed-range__title"><span><Gauge size={16} />Velocidade operacional</span><strong>{minSpeed}–{maxSpeed} km/h</strong></div><p>Faixa média adotada pela Seven Cargo, diferente do limite máximo da rodovia.</p><div><label><span>Mínima</span><input type="number" min="20" max="100" value={minSpeed} onChange={(e) => setMinSpeed(Number(e.target.value))} /></label><label><span>Máxima</span><input type="number" min="20" max="100" value={maxSpeed} onChange={(e) => setMaxSpeed(Number(e.target.value))} /></label></div></div>
        <section className="trip-simulator"><div className="trip-simulator__head"><div><span className="eyebrow">Estimativa independente</span><h3>Parâmetros da viagem</h3></div>{distanceOverride&&<button type="button" onClick={()=>setDistanceOverride('')}><RotateCcw/>Restaurar</button>}</div><div className="trip-simulator__fields"><label><span>Quilometragem</span><input type="number" min="1" step=".1" value={distanceOverride||catalogDistance.toFixed(1)} onChange={e=>setDistanceOverride(e.target.value)}/><small>{distanceOverride?'Ajuste manual':'Geometria salva'} · km</small></label><label><span>Paradas</span><input type="number" min="0" step="15" value={stopMinutes} onChange={e=>setStopMinutes(Math.max(0,Number(e.target.value)))}/><small>minutos</small></label><label><span>Margem</span><input type="number" min="0" max="100" value={marginPercent} onChange={e=>setMarginPercent(Math.max(0,Number(e.target.value)))}/><small>percentual</small></label></div><div className="trip-simulator__summary"><div><span>Em movimento</span><strong>{formatDuration(drivingMinutes)}</strong></div><div><span>Duração total</span><strong>{formatDuration(totalMinutes)}</strong></div><div><span>Chegada prevista</span><strong>{Number.isFinite(simulatedArrival.getTime())?simulatedArrival.toLocaleString('pt-BR'):'—'}</strong></div></div></section>
        <CostCalculator values={{dieselPrice,fuelConsumption,tolls,fuelBudget,operatingCostOverride,driverDaily,foodDaily,lodgingDaily,loadingCosts,otherCosts,commissionPercent,contingencyPercent,targetMarginPercent,freightValue}} setters={{setDieselPrice,setFuelConsumption,setTolls,setFuelBudget,setOperatingCostOverride,setDriverDaily,setFoodDaily,setLodgingDaily,setLoadingCosts,setOtherCosts,setCommissionPercent,setContingencyPercent,setTargetMarginPercent,setFreightValue}} result={{distance:simulatedDistance,driverDays,fuelCost,calculatedFuelCost,driverCost,commissionCost,contingencyCost,totalTripCost,calculatedTripCost,minimumFreight,estimatedProfit,estimatedMargin}} routeName={selectedCatalogRoute?.name} onSave={saveCostBase} saved={costBaseSaved} />
        <label><span>Data e hora de saída</span><div className="departure-row"><div className="field"><Clock3 size={18} /><input type="datetime-local" required value={departure} onChange={(e) => setDeparture(e.target.value)} /></div><button type="button" onClick={setDepartureNow}>Iniciar agora</button></div></label>
        {minSpeed > maxSpeed && <div className="form-error">A velocidade mínima não pode ser maior que a máxima.</div>}
        {preview.error && <div className="form-error">{preview.error.message}</div>}
        <div className="route-primary-actions"><button type="button" className="secondary-button simulation-button" disabled={!selectedCatalogRoute} onClick={()=>{if(simulationProgress>=100)setSimulationProgress(0);setSimulationRunning(value=>!value)}}>{simulationRunning?<><Pause/>Pausar</>:<><Play/>{simulationProgress>0?'Continuar':'Iniciar simulação'}</>}</button><button className="primary-button" disabled={preview.isPending || minSpeed > maxSpeed}>{preview.isPending ? 'Analisando trechos...' : 'Calcular rota operacional'}<ArrowRight size={18} /></button></div>
      </form>
    </section>
    <RouteResult route={preview.data} catalogRoute={selectedCatalogRoute} requestedWaypoints={waypoints.filter(Boolean)} requestedSpeed={[minSpeed, maxSpeed]} simulation={{progress:simulationProgress,speed:simulationSpeed,running:simulationRunning,totalMinutes,departure,distance:simulatedDistance,onSpeed:setSimulationSpeed,onReset:()=>{setSimulationProgress(0);setSimulationRunning(false)}}} />
  </div>
}

type CostKey = 'dieselPrice'|'fuelConsumption'|'tolls'|'fuelBudget'|'operatingCostOverride'|'driverDaily'|'foodDaily'|'lodgingDaily'|'loadingCosts'|'otherCosts'|'commissionPercent'|'contingencyPercent'|'targetMarginPercent'|'freightValue'
type CostValues = Record<CostKey,number>
type CostSetters = Record<`set${Capitalize<CostKey>}`,Dispatch<SetStateAction<number>>>
interface CostResult {distance:number;driverDays:number;fuelCost:number;calculatedFuelCost:number;driverCost:number;commissionCost:number;contingencyCost:number;totalTripCost:number;calculatedTripCost:number;minimumFreight:number;estimatedProfit:number;estimatedMargin:number}

function CostCalculator({values,setters,result,routeName,onSave,saved}:{values:CostValues;setters:CostSetters;result:CostResult;routeName?:string;onSave:()=>void;saved:boolean}) {
  const field=(label:string,key:CostKey,suffix:string,step='1')=>{const setter=setters[`set${key[0].toUpperCase()}${key.slice(1)}` as keyof CostSetters];return <label><span>{label}</span><div className="cost-input"><input type="number" min="0" step={step} value={values[key]} onChange={event=>setter(Math.max(0,Number(event.target.value)))}/><small>{suffix}</small></div></label>}
  const scenarios=[{name:'Econômico',factor:.95},{name:'Provável',factor:1},{name:'Conservador',factor:1.1}]
  return <section className="cost-calculator">
    <div className="cost-calculator__head"><div><span className="eyebrow">Análise para negociação</span><h3><Calculator/>Custo estimado da viagem</h3><small>{routeName||'Rota livre'} · todos os valores são editáveis</small></div><strong>{money(result.totalTripCost)}</strong></div>
    <div className="cost-highlight"><div><Fuel/><span>Combustível</span><strong>{money(result.fuelCost)}</strong><small>{values.fuelConsumption.toLocaleString('pt-BR')} km/L</small></div><div><Wallet/><span>Motorista</span><strong>{money(result.driverCost)}</strong><small>{result.driverDays} diária(s)</small></div><div><TrendingUp/><span>Frete mínimo</span><strong>{money(result.minimumFreight)}</strong><small>margem-alvo de {values.targetMarginPercent}%</small></div></div>
    <details open><summary>Combustível e estrada</summary><div className="cost-fields">{field('Combustível orçado','fuelBudget','R$','.01')}{field('Preço do diesel','dieselPrice','R$/L','.01')}{field('Consumo','fuelConsumption','km/L','.1')}{field('Pedágios','tolls','R$','.01')}{field('Carga e descarga','loadingCosts','R$','.01')}</div><p className="cost-hint">Cálculo por diesel: {money(result.calculatedFuelCost)}. Se “Combustível orçado” for maior que zero, ele prevalece.</p></details>
    <details><summary>Motorista e demais despesas</summary><div className="cost-fields">{field('Diária do motorista','driverDaily','R$','.01')}{field('Alimentação/dia','foodDaily','R$','.01')}{field('Hospedagem/dia','lodgingDaily','R$','.01')}{field('Outros custos','otherCosts','R$','.01')}</div></details>
    <details open><summary>Condição comercial</summary><div className="cost-fields">{field('Frete oferecido','freightValue','R$','.01')}{field('Custo operacional total','operatingCostOverride','R$','.01')}{field('Comissão','commissionPercent','%','.1')}{field('Imprevistos','contingencyPercent','%','.1')}{field('Margem desejada','targetMarginPercent','%','.1')}</div><p className="cost-hint">Cálculo detalhado: {money(result.calculatedTripCost)}. Se o custo operacional total for informado, ele prevalece como base oficial da negociação.</p></details>
    <div className="cost-breakdown"><span>Combustível <b>{money(result.fuelCost)}</b></span><span>Motorista <b>{money(result.driverCost)}</b></span><span>Comissão <b>{money(result.commissionCost)}</b></span><span>Reserva <b>{money(result.contingencyCost)}</b></span><span>Custo/km <b>{money(result.distance>0?result.totalTripCost/result.distance:0)}</b></span></div>
    <div className="negotiation-result"><div><span>Frete informado</span><strong>{values.freightValue>0?money(values.freightValue):'—'}</strong></div><div className={values.freightValue<=0?'':result.estimatedProfit>=0?'positive':'negative'}><span>{values.freightValue<=0?'Informe o frete':result.estimatedProfit>=0?'Lucro estimado':'Prejuízo estimado'}</span><strong>{values.freightValue>0?money(Math.abs(result.estimatedProfit)):'—'}</strong></div><div className={values.freightValue<=0?'':result.estimatedMargin>=values.targetMarginPercent?'positive':'warning'}><span>Margem</span><strong>{values.freightValue>0?`${result.estimatedMargin.toFixed(1)}%`:'—'}</strong></div></div>
    <div className="cost-scenarios">{scenarios.map(scenario=>{const cost=result.totalTripCost*scenario.factor;const suggested=result.minimumFreight*scenario.factor;return <article className={scenario.name==='Provável'?'active':''} key={scenario.name}><span>{scenario.name}</span><strong>{money(suggested)}</strong><small>Custo {money(cost)}</small></article>})}</div>
    <button type="button" className="save-cost-base" disabled={!routeName} onClick={onSave}>{saved?'Base salva para esta rota':'Salvar como base desta rota'}</button>
    <p className="cost-disclaimer">Estimativa gerencial para negociação. Confirme pedágios, jornada, impostos e regras da operação antes de fechar o frete.</p>
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
function readCostBase(routeId:string):Partial<Pick<CostValues,'freightValue'|'tolls'|'fuelBudget'|'operatingCostOverride'>>|null{try{const value=localStorage.getItem(`seven:route-cost:${routeId}`);return value?JSON.parse(value):null}catch{return null}}
function trafficExplanation(route: RoutePreview): string { if (route.traffic_delay_minutes === 0) return 'O provedor não mediu acréscimo de trânsito neste instante. A previsão operacional ainda considera a velocidade média do caminhão e não garante pista livre em todos os trechos.'; const live = route.live_traffic_delay_minutes > 0 ? ` Deste total, ${formatDuration(route.live_traffic_delay_minutes)} são de trânsito ao vivo em ${route.traffic_length_km.toLocaleString('pt-BR')} km monitorados.` : ' A diferença disponível é uma previsão histórica; não há atraso ao vivo retornado.'; return `${formatDuration(route.traffic_delay_minutes)} de acréscimo em relação ao fluxo livre.${live}` }
function ResultMetric({ icon: Icon, label, value }: { icon: typeof RouteIcon; label: string; value: string }) { return <div><i><Icon size={20} /></i><span>{label}</span><strong>{value}</strong></div> }
