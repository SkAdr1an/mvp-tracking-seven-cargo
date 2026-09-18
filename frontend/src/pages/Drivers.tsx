import { Check, Clock3, EyeOff, MapPin, RotateCcw, Search, Truck, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { DriverDiagnostic } from '../components/DriverDiagnostic'
import { OperationalTripPanel } from '../components/OperationalTripPanel'
import { DelayAccountabilityPanel } from '../components/DelayAccountabilityPanel'
import { progressLabel } from '../driverPresentation'
import type { Driver } from '../types'
import { formatAgo, formatDuration } from '../utils'

type DriverOrder = 'priority' | 'driver' | 'updated'

type Props = {
  drivers: Driver[]
  selected?: Driver
  hiddenDriverIds: string[]
  pinnedDriverId?: string
  onSelect: (driver: Driver) => void
  onClear: () => void
  onHide: (id: string) => void
  onRestore: (id: string) => void
  onRestoreAll: () => void
  onPin: (id: string) => void
}

export function Drivers({drivers,selected,hiddenDriverIds,pinnedDriverId,onSelect,onClear,onHide,onRestore,onRestoreAll,onPin}:Props) {
  const [search,setSearch]=useState('')
  const [classification,setClassification]=useState('all')
  const [order,setOrder]=useState<DriverOrder>('priority')
  const visible=drivers.filter((driver)=>!hiddenDriverIds.includes(driver.id))
  const hidden=drivers.filter((driver)=>hiddenDriverIds.includes(driver.id))
  const filtered=useMemo(()=>visible
    .filter((driver)=>`${driver.id} ${driver.driver||''} ${driver.trailer_plate||''} ${driver.route||''}`.toLowerCase().includes(search.toLowerCase())&&(classification==='all'||driver.prediction?.classification===classification))
    .sort((left,right)=>compareDrivers(left,right,order)),[visible,search,classification,order])
  return <div className="page-stack drivers-page">
    <DelayAccountabilityPanel/>
    <section className="panel table-panel">
      <div className="table-toolbar"><div><span className="eyebrow">Fonte principal · Trafegus</span><h2>Motoristas em andamento</h2><p className="toolbar-help">Clique em um motorista para abrir o diagnóstico operacional nesta aba.</p></div><div className="filters"><label className="search"><Search size={17}/><span className="sr-only">Buscar motorista, placa ou rota</span><input value={search} onChange={(event)=>setSearch(event.target.value)} placeholder="Buscar placa ou motorista"/></label><label className="filter-field"><span className="sr-only">Filtrar por situação</span><select value={classification} onChange={(event)=>setClassification(event.target.value)}><option value="all">Todas as situações</option><option value="NORMAL">Normal</option><option value="ATENCAO">Atenção</option><option value="CRITICA">Crítica</option></select></label><label className="filter-field driver-order"><span className="sr-only">Ordenar motoristas</span><select value={order} onChange={(event)=>setOrder(event.target.value as DriverOrder)}><option value="priority">Prioridade operacional</option><option value="driver">Motorista / veículo</option><option value="updated">Atualização mais recente</option></select></label></div></div>
      <div className="data-table fleet-table driver-management-table"><div className="data-table__head"><span>Veículo / motorista</span><span>Situação</span><span>Localização</span><span>ETA / atraso</span><span>Comunicação</span><span>Ações</span></div>
        {filtered.map((driver)=><div className={`data-table__row driver-card ${pinnedDriverId===driver.id?'data-table__row--pinned':''} ${selected?.id===driver.id?'data-table__row--selected':''}`} key={driver.trip_id||driver.id}><button className="driver-open" onClick={()=>onSelect(driver)} aria-label={`Abrir diagnóstico de ${driver.driver||driver.id}, ${classificationLabel(driver.prediction?.classification)}`}><span className="driver-cell"><i><Truck size={18}/></i><span><strong>{driver.id}{driver.trailer_plate?` · ${driver.trailer_plate}`:''}</strong><small>{driver.driver||'Motorista não informado'}</small></span></span><span className="driver-card__classification"><Classification value={driver.prediction?.classification}/></span><span className="visual-cell driver-card__location"><MapPin size={14}/>{driver.location_description||'Posição sem descrição'}</span><span className="driver-card__eta">{driver.prediction?.eta_at?new Date(driver.prediction.eta_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'Não calculado'}{driver.prediction?.delay_minutes?<small className="stale">+{formatDuration(driver.prediction.delay_minutes)}</small>:null}</span><span className="visual-cell driver-card__updated"><Clock3 size={14}/>{formatAgo(driver.last_update)}{driver.stale&&<small className="stale">Posição desatualizada</small>}</span><span className="driver-card__mobile-summary"><small><b>Rota</b>{driver.route||'Não informada'}</small><small><b>Sentido</b>{tripDirection(driver)}</small><small><b>Progresso</b>{progressLabel(driver)}</small><small><b>Atualização</b>{formatAgo(driver.last_update)}</small></span></button><div className="management-actions"><button title="Fixar no monitoramento" aria-label={`Fixar ${driver.id} no monitoramento`} aria-pressed={pinnedDriverId===driver.id} className={pinnedDriverId===driver.id?'active':''} onClick={()=>onPin(driver.id)}><Check size={17}/></button><button title="Ocultar temporariamente" aria-label={`Ocultar ${driver.id} temporariamente`} onClick={()=>onHide(driver.id)}><X size={17}/></button></div></div>)}
        {!filtered.length&&<div className="table-empty">Nenhuma viagem encontrada para este filtro.</div>}
      </div>
    </section>
    {selected && !hiddenDriverIds.includes(selected.id) && <>
      <DriverDiagnostic driver={selected} onClose={onClear}/>
      {selected.operational && <OperationalTripPanel initial={selected.operational}/>}
    </>}
    {!!hidden.length&&<section className="panel hidden-management"><div><span className="eyebrow">Ocultação somente visual</span><h2><EyeOff size={19}/>Motoristas ocultos</h2><p>Nenhum dado, vínculo ou histórico foi excluído.</p></div><div className="hidden-management__actions"><button className="secondary-button" onClick={onRestoreAll}><RotateCcw size={15}/>Restaurar todos</button></div><div className="hidden-management__list">{hidden.map((driver)=><article key={driver.id}><span className="vehicle-icon"><Truck size={18}/></span><div><strong>{driver.id}</strong><small>{driver.driver||'Não informado'}</small></div><button onClick={()=>onRestore(driver.id)}><RotateCcw size={14}/>Restaurar</button></article>)}</div></section>}
  </div>
}

function Classification({value}:{value?:string}){return <em className={`trip-class trip-class--${value?.toLowerCase()||'unknown'}`}>{value==='ATENCAO'?'ATENÇÃO':value==='CRITICA'?'CRÍTICA':value||'SEM ETA'}</em>}
function classificationLabel(value?:string){return value==='ATENCAO'?'Atenção':value==='CRITICA'?'Crítica':value==='NORMAL'?'Normal':'Sem ETA'}
function tripDirection(driver:Driver){return driver.operational?.state==='RETORNO_SEVEN_CONFIRMADO'?'Retorno confirmado':'Ida'}
function compareDrivers(left:Driver,right:Driver,order:DriverOrder){
  if(order==='driver')return `${left.driver||''} ${left.id}`.localeCompare(`${right.driver||''} ${right.id}`,'pt-BR')
  if(order==='updated')return timestamp(right.last_update)-timestamp(left.last_update)
  const priority=(value?:string)=>value==='CRITICA'?0:value==='ATENCAO'?1:value==='NORMAL'?2:3
  return priority(left.prediction?.classification)-priority(right.prediction?.classification)||timestamp(right.last_update)-timestamp(left.last_update)
}
function timestamp(value?:string){const parsed=value?new Date(value).getTime():0;return Number.isFinite(parsed)?parsed:0}
