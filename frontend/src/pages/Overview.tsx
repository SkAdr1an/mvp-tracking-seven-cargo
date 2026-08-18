import { AlertTriangle, ArrowRight, ChevronDown, Clock3, CloudLightning, List, Radio, RotateCcw, Route, ShieldCheck, Truck } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { DriverMap } from '../components/DriverMap'
import type { MapCameraCommand } from '../components/MapResizeController'
import { OperationalTripPanel } from '../components/OperationalTripPanel'
import type { Driver, FleetSnapshot, OperationalSite, RoutePaths, TrafficIncident, TrafficSnapshot } from '../types'
import { formatAgo } from '../utils'
import { operationalAvailability } from '../driverPresentation'
import { currentDeviationDriverIds } from '../overviewMetrics'

type Filter = 'trips'|'normal'|'attention'|'critical'|'off_route'|'accident'|'works'|'slow'|'weather'

export function Overview({drivers,selected,hiddenDriverIds,pinnedDriverId,onSelect,onClear,onOpenDrivers,fleet,source,traffic,paths,sites,onTrafficChanged}:{drivers:Driver[];selected?:Driver;hiddenDriverIds:string[];pinnedDriverId?:string;onSelect:(driver:Driver)=>void;onClear:()=>void;onOpenDrivers:()=>void;fleet?:FleetSnapshot;source:'trafegus'|'websocket';traffic?:TrafficSnapshot;paths?:RoutePaths;sites:OperationalSite[];onTrafficChanged:()=>unknown}) {
  const [filter,setFilter]=useState<Filter>()
  const [cameraCommand,setCameraCommand]=useState<MapCameraCommand>({id:0,mode:'fit'})
  const [showMoreMetrics,setShowMoreMetrics]=useState(false)
  const deviations=useMemo(()=>currentDeviationDriverIds(drivers,paths),[drivers,paths])
  const incidents=traffic?.incidents||[]
  const visible=drivers.filter((driver)=>!hiddenDriverIds.includes(driver.id))
  const shown=visible.filter((driver)=>matchesDriver(driver,filter,deviations.has(driver.id),incidents))
  const shownIncidents=incidents.filter((item)=>matchesIncident(item,filter))
  const focused=shown.find((driver)=>driver.id===selected?.id)
  const selectedVisible=!selected||shown.some((driver)=>driver.id===selected.id)
  const fitVisible=useCallback(()=>setCameraCommand((current)=>({id:current.id+1,mode:'fit'})),[])
  const changeFilter=(next?:Filter)=>{setFilter(next);if(selected&&!visible.some((driver)=>driver.id===selected.id&&matchesDriver(driver,next,deviations.has(driver.id),incidents)))onClear();fitVisible()}
  const selectVisibleDriver=(driver:Driver)=>{if(selected?.id===driver.id){onClear();fitVisible();return}onSelect(driver);setCameraCommand((current)=>driver.location?{id:current.id+1,mode:'focus',point:[driver.location.latitude,driver.location.longitude]}:{id:current.id+1,mode:'fit'})}
  useEffect(()=>{if(selected&&!selectedVisible)onClear()},[onClear,selected,selectedVisible])
  const counts=fleet?.counts
  const metrics:Array<[Filter,typeof Truck,string,number,string,string]>=[
    ['trips',Truck,'Viagens em andamento',counts?.total??drivers.length,source==='trafegus'?'Fonte: Trafegus':'Fallback WebSocket','green'],
    ['normal',ShieldCheck,'Normais',counts?.normal??0,'Dentro da previsão','blue'],
    ['attention',AlertTriangle,'Em atenção',counts?.attention??0,'Exigem acompanhamento','amber'],
    ['critical',AlertTriangle,'Críticas',counts?.critical??0,'Prioridade operacional','red'],
    ['off_route',Route,'Fora da rota',deviations.size,'Desvios confirmados em viagens ativas','red'],
    ['accident',AlertTriangle,'Acidentes',traffic?.counts.ACIDENTE??0,'Ocorrências ativas','red'],
    ['works',Route,'Obras/interdições',traffic?.counts.OBRA_INTERDICAO??0,'Impactos na via','amber'],
    ['slow',Clock3,'Trechos lentos',traffic?.counts.TRECHO_LENTO??0,'Fluxo comprometido','amber'],
    ['weather',CloudLightning,'Riscos climáticos',counts?.weather_risks??0,'Próximos trechos','amber'],
  ]
  return <div className="page-stack premium-overview">
    <section className={`metrics-grid overview-metrics ${showMoreMetrics?'overview-metrics--expanded':''}`}>{metrics.map(([key,icon,label,value,detail,tone],index)=><Metric key={key} icon={icon} label={label} value={value} detail={detail} tone={tone} secondary={index>=4} active={filter===key} onClick={()=>changeFilter(filter===key?undefined:key)}/>)}</section>
    <div className="overview-mobile-actions"><button onClick={onOpenDrivers}><List size={17}/>Abrir lista de motoristas</button><button aria-expanded={showMoreMetrics} onClick={()=>setShowMoreMetrics((value)=>!value)}><ChevronDown size={17}/>{showMoreMetrics?'Ocultar indicadores':'Outros indicadores'}</button></div>
    {filter&&<button className="clear-filters" onClick={()=>changeFilter(undefined)}><RotateCcw size={15}/>Limpar filtros</button>}
    {fleet?.warning&&<div className="error-banner"><AlertTriangle size={18}/><div><strong>Operação em modo degradado</strong><span>{fleet.warning}</span></div></div>}
    <section className="operations-grid">
      <div className="panel map-panel"><div className="panel__header"><div><span className="eyebrow">Trafegus · atualização automática</span><h2>Frota em tempo real</h2></div><span className="live-label"><i/>{fleet?.source_status==='stale'?'CACHE':'AO VIVO'}</span></div><DriverMap drivers={shown} selected={focused} pinnedId={pinnedDriverId} paths={paths?.paths||[]} sites={sites} onSelect={selectVisibleDriver} cameraCommand={cameraCommand} traffic={traffic?{...traffic,incidents:shownIncidents}:undefined} onTrafficChanged={onTrafficChanged}/></div>
      <div className="panel fleet-panel"><div className="panel__header"><div><span className="eyebrow">Viagens ativas</span><h2>Situação da frota</h2></div><span className="count-pill">{shown.length}</span></div>
        <div className="driver-list">{!shown.length&&<div className="empty-list"><Radio size={27}/><strong>Nenhuma viagem neste filtro</strong><span>Os dados operacionais não foram alterados.</span></div>}{shown.map((driver)=><button key={driver.trip_id||driver.id} className={`driver-row driver-row--clean ${focused?.id===driver.id?'driver-row--selected':''} ${pinnedDriverId===driver.id?'driver-row--pinned':''}`} onClick={()=>selectVisibleDriver(driver)}><div className={`vehicle-icon vehicle-icon--${driver.status}`}><Truck size={19}/></div><div className="driver-row__main"><strong className="driver-telemetry" title="Velocidade e distância estimadas pelo último snapshot"><b>{driver.id}</b><i/> <span>{speedLabel(driver)}</span><i/> <span>{remainingLabel(driver)}</span></strong><span>{driver.driver||'Motorista não informado'}</span><small>{driver.route||driver.location_description||'Rota não informada'}</small></div><div className="driver-row__meta"><Classification value={driver.prediction?.classification}/><span>{formatAgo(driver.last_update)}</span></div></button>)}</div>
        <button className="fleet-panel__all" onClick={onOpenDrivers}>Ver todas as viagens <ArrowRight size={15}/></button>
      </div>
    </section>
    {focused&&<section className="panel trip-detail"><div className="trip-detail__heading"><div><span className="eyebrow">Viagem selecionada</span><h2>{focused.id}</h2><p>{focused.driver||'Motorista não informado'} · {focused.tracker||'Rastreador não informado'}</p></div><Classification value={focused.prediction?.classification}/></div><ProgressDetail driver={focused}/>{focused.operational&&<OperationalTripPanel initial={focused.operational}/>}</section>}
    <div className="fleet-freshness"><Clock3 size={14}/>Última atualização da frota: {fleet?.generated_at?new Date(fleet.generated_at).toLocaleString('pt-BR'):'aguardando Trafegus'}</div>
  </div>
}

function Metric({icon:Icon,label,value,detail,tone,secondary,active,onClick}:{icon:typeof Truck;label:string;value:number;detail:string;tone:string;secondary:boolean;active:boolean;onClick:()=>void}){return <button className={`metric metric--filter ${secondary?'metric--secondary':''} ${active?'metric--active':''}`} aria-pressed={active} onClick={onClick}><div className={`metric__icon metric__icon--${tone}`}><Icon size={21}/></div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></button>}
function Classification({value}:{value?:string}){const label=value==='CRITICA'?'CRÍTICA':value==='ATENCAO'?'ATENÇÃO':value||'SEM ETA';return <em className={`trip-class trip-class--${value?.toLowerCase()||'unknown'}`}>{label}</em>}
function speedLabel(driver:Driver){const progress=driver.route_progress;if(progress?.speed_state==='STALE'||driver.stale)return 'Velocidade desatualizada';if(progress?.speed_state==='UNAVAILABLE'||progress?.speed_kmh==null)return 'Sem velocidade';return `${Math.round(progress.speed_kmh)} km/h`}
function remainingLabel(driver:Driver){if(driver.route_recognition?.status==='GEOMETRY_PENDING')return 'Geometria pendente';if(driver.route_recognition?.status==='AMBIGUOUS')return 'Rota ambígua';if(driver.route_recognition?.status==='UNIDENTIFIED')return 'Rota não identificada';const value=driver.route_progress?.remaining_distance_km;return value==null?'Distância indisponível':`${Math.round(value)} km restantes`}
function ProgressDetail({driver}:{driver:Driver}){const issue=operationalAvailability(driver);if(issue)return <div className="progress-unavailable" data-diagnostic-code={issue.code}><strong>{issue.message}</strong><br/><span>Os demais dados válidos da viagem permanecem disponíveis.</span></div>;const value=driver.route_progress;if(!value)return <div className="progress-unavailable" data-diagnostic-code="OPERATIONAL_DATA_INCOMPLETE">Estimativa de progresso indisponível para esta viagem.</div>;const state=value.route_state==='ON_ROUTE'?'Dentro da rota':value.route_state==='OUTSIDE'?'Fora da rota':'Posição desatualizada';const confidence={HIGH:'Alta',MEDIUM:'Média',LOW:'Baixa',UNAVAILABLE:'Indisponível'}[value.confidence];return <div className="route-progress-detail"><div className="route-progress-stats"><ProgressValue label="Velocidade atual" value={speedLabel(driver)}/><ProgressValue label="Última leitura" value={value.position_at?new Date(value.position_at).toLocaleString('pt-BR'):'Indisponível'}/><ProgressValue label="Distância oficial total" value={`${value.total_distance_km.toLocaleString('pt-BR')} km`}/><ProgressValue label="Avançado sobre a rota" value={`${value.advanced_distance_km.toLocaleString('pt-BR')} km`}/><ProgressValue label="Restante pela rota oficial" value={`${value.remaining_distance_km.toLocaleString('pt-BR')} km`}/><ProgressValue label="ETA atual" value={driver.prediction?.eta_at?new Date(driver.prediction.eta_at).toLocaleString('pt-BR'):'Indisponível'}/><ProgressValue label="Situação" value={state}/><ProgressValue label="Confiabilidade" value={confidence}/>{value.return_distance_km!=null&&<ProgressValue label="Retorno aproximado à rota" value={`${value.return_distance_km.toLocaleString('pt-BR')} km`}/>}</div><div className="route-progress-bar"><div><span>Progresso pela geometria oficial</span><strong>{value.progress_percent.toLocaleString('pt-BR')}%</strong></div><progress max="100" value={value.progress_percent}/><small>Geometria {value.geometry_version}{value.confidence==='LOW'?' · última estimativa confiável preservada':''}</small></div></div>}
function ProgressValue({label,value}:{label:string;value:string}){return <div><span>{label}</span><strong>{value}</strong></div>}
function matchesDriver(driver:Driver,filter:Filter|undefined,offRoute:boolean,incidents:TrafficIncident[]){if(!filter||filter==='trips')return true;if(filter==='off_route')return offRoute;if(filter==='normal'||filter==='attention'||filter==='critical')return driver.prediction?.classification===(filter==='normal'?'NORMAL':filter==='attention'?'ATENCAO':'CRITICA');if(filter==='weather')return !!driver.weather_risks?.length;return incidents.filter((item)=>matchesIncident(item,filter)).some((item)=>item.affected_vehicles.some((vehicle)=>vehicle.plate===driver.id))}
function matchesIncident(item:TrafficIncident,filter:Filter|undefined){if(!filter||['trips','normal','attention','critical','off_route'].includes(filter))return true;if(filter==='accident')return item.category==='ACIDENTE';if(filter==='works')return ['OBRA','INTERDICAO','VIA_FECHADA'].includes(item.category);if(filter==='slow')return ['CONGESTIONAMENTO','TRANSITO_LENTO'].includes(item.category);return filter==='weather'&&item.category==='RISCO_CLIMATICO'}
