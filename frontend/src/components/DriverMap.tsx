import { Circle, CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMapEvents } from 'react-leaflet'
import { divIcon } from 'leaflet'
import { FormEvent, useMemo, useState } from 'react'
import { Layers3, X } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import type { Driver, OperationalSite, TrafficSnapshot, VehiclePath } from '../types'
import { formatAgo, formatDuration } from '../utils'
import { api } from '../api'
import { usePermission } from '../permissions'
import { clusterTrafficIncidents, completedRoute, filterTrafficIncidents } from './mapUtils'
import { HomologatedStationsLayer } from './HomologatedStationsLayer'
import { MapResizeController, type MapCameraCommand } from './MapResizeController'
import '../mobile-map.css'

type Filters = { trucks:boolean; traffic:boolean; weather:boolean; fences:boolean; sites:boolean; siteRadii:boolean; manual:boolean; stations:boolean }
function PickCoordinate({ enabled,onPick }:{enabled:boolean;onPick:(lat:number,lon:number)=>void}) { useMapEvents({click(event){if(enabled)onPick(event.latlng.lat,event.latlng.lng)}});return null }

export function DriverMap({ drivers,selected,pinnedId,paths,sites,onSelect,cameraCommand,traffic,onTrafficChanged }:{drivers:Driver[];selected?:Driver;pinnedId?:string;paths:VehiclePath[];sites:OperationalSite[];onSelect:(driver:Driver)=>void;cameraCommand:MapCameraCommand;traffic?:TrafficSnapshot;onTrafficChanged:()=>unknown}) {
  const canCreateIncident=usePermission('incidents:create')
  const [filters,setFilters]=useState<Filters>({trucks:true,traffic:true,weather:true,fences:true,sites:true,siteRadii:true,manual:true,stations:false})
  const [manualOpen,setManualOpen]=useState(false); const [point,setPoint]=useState<{lat:number;lon:number}>();
  const [filtersOpen,setFiltersOpen]=useState(false)
  const stations=useQuery({queryKey:['angellira','validated-stations'],queryFn:api.angelLiraStations,enabled:filters.stations,staleTime:30*60*1000})
  const incidents=filterTrafficIncidents(traffic?.incidents||[],filters.traffic,filters.manual)
  const clusters=useMemo(()=>clusterTrafficIncidents(incidents),[incidents])
  const weather=drivers.flatMap((driver)=>(driver.weather_risks||[]).map((risk,index)=>({id:`${driver.id}-${index}`,driver,risk})))
  const progressLines=useMemo(()=>drivers.flatMap((driver)=>{
    const path=paths.find((item)=>item.trip_key===driver.operational?.trip_key)
    const routeId=driver.operational?.route_id||path?.route_id
    const route=traffic?.routes.find((item)=>item.id===routeId)
    const points=completedRoute(route?.geometry||[],driver.location)
    return points.length>1?[{tripKey:driver.operational?.trip_key||driver.trip_id||driver.id,driver,points,path}]:[]
  }),[drivers,paths,traffic?.routes])
  const viewportPoints=useMemo(()=>[
    ...(filters.trucks?drivers.flatMap((driver)=>driver.location?[[driver.location.latitude,driver.location.longitude] as [number,number]]:[]):[]),
  ],[drivers,filters.trucks])
  return <div className="map-shell operational-map">
    <MapContainer center={[-14.1,-39.6]} zoom={5} zoomControl className="map">
      <MapResizeController points={viewportPoints} command={cameraCommand}/>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {traffic?.routes.map((route)=><Polyline key={route.id} positions={route.geometry.map((p)=>[p.latitude,p.longitude])} pathOptions={{color:'#d39f18',weight:3,opacity:.55,dashArray:'10 10'}}><Tooltip sticky>Rota planejada</Tooltip></Polyline>)}
      {progressLines.map(({tripKey,driver,points,path})=>{const highlighted=(selected?.id||pinnedId)===driver.id;return <Polyline key={`progress-${tripKey}`} positions={points.map((point)=>[point.latitude,point.longitude])} pathOptions={{color:path?.deviation?'#ef6a5b':'#176b55',weight:highlighted?6:4,opacity:highlighted?1:(pinnedId?.length?.25:.78)}}><Tooltip sticky>{driver.id} · Progresso desde a origem</Tooltip></Polyline>})}
      {filters.sites&&sites.map((site)=><Marker key={`site-${site.id}`} position={[site.latitude,site.longitude]} icon={mapIcon('site','CD')}><Tooltip>CD · {site.name}</Tooltip><Popup><strong>CD · {site.name}</strong><br/>{site.operation}{site.address?<><br/>{site.address}</>:null}{site.municipality?<><br/>{site.municipality}</>:null}<br/>{site.aliases.length>1?<>Códigos: {site.aliases.join(' · ')}<br/></>:null}Raios: entrada 500 m · saída 650 m · aproximação 1.000 m</Popup></Marker>)}
      {filters.sites&&filters.siteRadii&&sites.flatMap((site)=>[
        <Circle key={`${site.id}-entry`} className="site-radius site-radius--entry" center={[site.latitude,site.longitude]} radius={site.entry_radius_m} pathOptions={{color:'#38d996',weight:2,fillOpacity:.035}}/>,
        <Circle key={`${site.id}-exit`} className="site-radius site-radius--exit" center={[site.latitude,site.longitude]} radius={site.exit_radius_m} pathOptions={{color:'#f2bd5b',weight:1.5,fillOpacity:0,dashArray:'6 5'}}/>,
        <Circle key={`${site.id}-approach`} className="site-radius site-radius--approach" center={[site.latitude,site.longitude]} radius={site.approach_radius_m} pathOptions={{color:'#70a5ff',weight:1,fillOpacity:0,dashArray:'3 7'}}/>,
      ])}
      {filters.trucks&&drivers.filter((driver)=>driver.location).map((driver)=>{const classification=driver.prediction?.classification;const color=driver.stale?'#718079':classification==='CRITICA'?'#ef6a5b':classification==='ATENCAO'?'#f2bd5b':'#e8b923';const ahead=(traffic?.incidents||[]).filter((item)=>item.affected_vehicles.some((vehicle)=>vehicle.plate===driver.id));const site=driver.operational_site;return <CircleMarker key={driver.id} center={[driver.location!.latitude,driver.location!.longitude]} radius={selected?.id===driver.id?11:8} pathOptions={{color:'#fff',weight:2,fillColor:color,fillOpacity:1}} eventHandlers={{click:()=>onSelect(driver)}}><Tooltip direction="top">{driver.id} · {siteStateLabel(site?.state)}</Tooltip><Popup><strong>{driver.id}{driver.trailer_plate?` · ${driver.trailer_plate}`:''}</strong><br/>{driver.driver||'Motorista não informado'}<br/>CD: {siteStateLabel(site?.state)}{site?.site_name?<><br/>{site.site_name} · {site.distance_m?.toLocaleString('pt-BR')} m</>:null}<br/>Estado da viagem: {driver.operational?.state||'Não classificado'}<br/>Velocidade: {driver.location?.speed_kmh!=null?`${driver.location.speed_kmh} km/h`:'Não informada'}<br/>Atualizado {formatAgo(driver.last_update)}<br/>ETA: {driver.prediction?.eta_at?new Date(driver.prediction.eta_at).toLocaleString('pt-BR'):'Não calculado'}<br/>SLA: {driver.prediction?.sla_at?new Date(driver.prediction.sla_at).toLocaleString('pt-BR'):'Não informado'}<br/><strong>{ahead.length} ocorrência(s) à frente</strong>{ahead[0]?<><br/>Mais relevante: {ahead[0].affected_vehicles.find((v)=>v.plate===driver.id)?.distance_along_route_km} km · atraso reportado {ahead[0].delay_seconds?formatDuration(ahead[0].delay_seconds/60):'não informado'} (não somado novamente ao ETA)</>:null}</Popup></CircleMarker>})}
      {clusters.map((cluster)=>{const critical=cluster.incidents.some((item)=>item.severity==='CRITICO');const main=cluster.incidents[0];return <Marker key={cluster.incidents.map((i)=>i.id).join('|')} position={[cluster.latitude,cluster.longitude]} icon={mapIcon(critical?'critical':main.manual?'manual':main.category,cluster.incidents.length>1?String(cluster.incidents.length):incidentLetter(main.category),critical)}><Tooltip>{cluster.incidents.length>1?`${cluster.incidents.length} ocorrências`:main.description}</Tooltip><Popup><strong>{cluster.incidents.length>1?`${cluster.incidents.length} ocorrências próximas`:main.category}</strong>{cluster.incidents.slice(0,5).map((item)=><div className="incident-popup" key={item.id}><b>{item.severity} · {item.category}</b><span>{item.road_name||item.description}</span><small>{item.direction?`Sentido ${item.direction} · `:''}{item.length_m?`${Math.round(item.length_m)} m · `:''}{item.delay_seconds?`atraso TomTom ${formatDuration(item.delay_seconds/60)} · `:''}{item.affected_vehicles.length} veículo(s) afetado(s)</small><small>{item.source} · atualizado {formatAgo(item.updated_at)}</small></div>)}</Popup></Marker>})}
      {filters.weather&&weather.map(({id,driver,risk})=><Marker key={id} position={[risk.position.latitude,risk.position.longitude]} icon={mapIcon('weather','C')}><Popup><strong>Risco climático</strong><br/>{risk.description}<br/>Possível impacto: {driver.id}<br/>{risk.source}</Popup></Marker>)}
      {filters.stations&&stations.data&&<HomologatedStationsLayer data={stations.data}/>}
      <PickCoordinate enabled={manualOpen} onPick={(lat,lon)=>setPoint({lat,lon})}/>
    </MapContainer>
    <button className="map-filters-toggle" type="button" aria-expanded={filtersOpen} aria-controls="operational-map-filters" onClick={()=>setFiltersOpen((value)=>!value)}><Layers3 size={18}/><span>Camadas</span></button>
    <div id="operational-map-filters" className={`map-filters ${filtersOpen?'map-filters--open':''}`} aria-label="Camadas do mapa">{([['trucks','Caminhões'],['traffic','Trânsito'],['weather','Clima'],['fences','Cercas de rota'],['sites','CDs'],['siteRadii','Raios dos CDs'],['manual','Manuais'],['stations','Postos homologados']] as const).map(([key,label])=><button type="button" key={key} aria-pressed={filters[key]} className={filters[key]?'active':''} onClick={()=>setFilters((value)=>({...value,[key]:!value[key]}))}>{label}</button>)}{canCreateIncident&&<button type="button" className="manual-add" onClick={()=>{setManualOpen((value)=>!value);setFiltersOpen(false)}}>+ Ocorrência</button>}</div>
    <div className="map__legend"><span><i className="dot dot--green"/>Normal</span><span><i className="dot dot--amber"/>Atenção</span><span><i className="dot dot--red"/>Crítica</span><span className="legend-route legend-route--planned">Rota planejada</span><span className="legend-route legend-route--actual">Percurso preenchido até o caminhão</span><span>CDs · entrada 500 m · saída 650 m · aproximação 1.000 m</span>{filters.stations&&<span className="station-layer-note">Postos: referência visual · AngelLira {stations.data?.dataset?.source_version||''}</span>}</div>
    {filters.stations&&stations.isLoading&&<div className="map-layer-status">Carregando postos homologados...</div>}
    {filters.stations&&stations.isError&&<div className="map-layer-status map-layer-status--error">Não foi possível carregar os postos. As demais camadas continuam disponíveis.</div>}
    {filters.stations&&stations.data&&!stations.data.stations.length&&<div className="map-layer-status">Nenhum posto validado para exibição exata.</div>}
    {canCreateIncident&&manualOpen&&<ManualIncidentForm routes={traffic?.routes||[]} point={point} onClose={()=>setManualOpen(false)} onSaved={()=>{setManualOpen(false);setPoint(undefined);onTrafficChanged()}}/>}
    {!drivers.some((driver)=>driver.location)&&<div className="map__empty"><strong>Aguardando o Trafegus</strong><span>A rota e as ocorrências continuam disponíveis.</span></div>}
  </div>
}

function ManualIncidentForm({routes,point,onClose,onSaved}:{routes:TrafficSnapshot['routes'];point?:{lat:number;lon:number};onClose:()=>void;onSaved:()=>void}) {
  const mutation=useMutation({mutationFn:api.createManualIncident,onSuccess:onSaved}); const [description,setDescription]=useState('');const [category,setCategory]=useState('OCORRENCIA_MANUAL');const [severity,setSeverity]=useState('ATENCAO');const [validHours,setValidHours]=useState(2)
  const submit=(event:FormEvent)=>{event.preventDefault();if(!point||!routes[0])return;const start=new Date();mutation.mutate({route_id:routes[0].id,category,description,latitude:point.lat,longitude:point.lon,severity,started_at:start.toISOString(),expires_at:new Date(start.getTime()+validHours*3600000).toISOString(),information_source:'Informação operacional não verificada',responsible_user:'operador',justification:'Registro operacional manual'})}
  return <form className="manual-incident-form" onSubmit={submit} aria-label="Nova ocorrência manual"><div><strong>Nova ocorrência manual</strong><button type="button" onClick={onClose} aria-label="Cancelar ocorrência"><X size={20}/></button></div><p aria-live="polite">{point?`${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`:'Toque no mapa para definir o local'}</p><label><span>Categoria</span><select value={category} onChange={(e)=>setCategory(e.target.value)}><option value="OCORRENCIA_MANUAL">Informação do motorista / outro</option><option value="CONGESTIONAMENTO">Fila</option><option value="INTERDICAO">Blitz ou restrição local</option><option value="RISCO_CLIMATICO">Alagamento</option><option value="OUTRO">Pane / protesto / outro</option></select></label><label><span>Descrição</span><input required minLength={5} placeholder="Descreva a ocorrência" value={description} onChange={(e)=>setDescription(e.target.value)}/></label><div><label><span>Severidade</span><select value={severity} onChange={(e)=>setSeverity(e.target.value)}><option value="INFORMATIVO">Informativo</option><option value="ATENCAO">Atenção</option><option value="CRITICO">Crítico</option></select></label><label><span>Validade em horas</span><input type="number" min="1" max="24" value={validHours} onChange={(e)=>setValidHours(Number(e.target.value))}/></label></div>{mutation.error&&<small role="alert">{mutation.error.message}</small>}<button className="primary-button" disabled={!point||mutation.isPending}>{mutation.isPending?'Salvando...':'Registrar ocorrência'}</button></form>
}

function incidentLetter(category:string){return category==='ACIDENTE'?'A':category==='OBRA'?'O':category==='VIA_FECHADA'||category==='INTERDICAO'?'B':category==='CONGESTIONAMENTO'||category==='TRANSITO_LENTO'?'L':'!'}
function siteStateLabel(state?:string){return state==='INSIDE'?'Dentro do CD':state==='APPROACHING'?'Aproximando-se':state==='OUTSIDE'?'Fora dos CDs':'Localização indisponível'}
function mapIcon(kind:string,label:string,critical=false){return divIcon({className:'map-div-icon',html:`<span class="map-symbol map-symbol--${kind}${critical?' map-symbol--pulse':''}">${label}</span>`,iconSize:[30,30],iconAnchor:[15,15]})}
