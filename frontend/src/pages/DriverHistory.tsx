import { Download, Search, UserRound } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { PanelGate } from '../components/PanelGate'
import type { DriverHistorySummary, DriverHistoryTrip, DriverProfile } from '../types'

export function DriverHistory({onConnection}:{onConnection?:(state:'connected'|'disconnected')=>void}){return <PanelGate onConnection={onConnection}><HistoryContent onConnection={onConnection}/></PanelGate>}

function HistoryContent({onConnection}:{onConnection?:(state:'connected'|'disconnected')=>void}){
  const [search,setSearch]=useState(''),[drivers,setDrivers]=useState<DriverHistorySummary[]>([]),[selected,setSelected]=useState<DriverHistorySummary>(),[profile,setProfile]=useState<DriverProfile>(),[trips,setTrips]=useState<DriverHistoryTrip[]>([]),[error,setError]=useState('')
  const [page,setPage]=useState(1),[total,setTotal]=useState(0)
  const [reportLoading,setReportLoading]=useState(false)
  const pageSize=25,totalPages=Math.max(1,Math.ceil(total/pageSize))
  const [start,setStart]=useState(''),[end,setEnd]=useState(''),[route,setRoute]=useState(''),[customer,setCustomer]=useState(''),[status,setStatus]=useState('')
  useEffect(()=>{setPage(1);setSelected(undefined);setProfile(undefined);setTrips([])},[search])
  useEffect(()=>{const handle=setTimeout(()=>api.driverHistory(search,page,pageSize).then(value=>{setDrivers(value.items);setTotal(value.total);setError('');onConnection?.('connected')}).catch(()=>{setError('Histórico indisponível. Verifique se a API está em execução e tente novamente.');onConnection?.('disconnected')}),250);return()=>clearTimeout(handle)},[search,page,onConnection])
  const query=useMemo(()=>new URLSearchParams(Object.entries({start,end,route,customer,status}).filter(([,v])=>v)).toString(),[start,end,route,customer,status])
  useEffect(()=>{if(!selected)return;Promise.all([api.driverProfile(selected.id),api.driverTrips(selected.id,query)]).then(([p,t])=>{setProfile(p);setTrips(t.items);setError('');onConnection?.('connected')}).catch(()=>{setError('Não foi possível carregar os detalhes deste motorista.');onConnection?.('disconnected')})},[selected,query,onConnection])
  async function downloadReport(){
    if(!profile||reportLoading)return
    setReportLoading(true);setError('')
    try{
      const {blob,filename}=await api.driverReport(profile.id,query)
      const url=URL.createObjectURL(blob),link=document.createElement('a')
      link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove()
      URL.revokeObjectURL(url)
    }catch(reason){
      setError(reason instanceof Error?reason.message:'Não foi possível gerar o relatório. Tente novamente.')
    }finally{setReportLoading(false)}
  }
  return <div className="page-stack history-page">
    <section className="panel history-search"><div><span className="eyebrow">Banco interno</span><h2>Histórico individual</h2><p>A consulta não depende do Trafegus. Selecione pelo ID interno ou CPF, usando nome, telefone e placa apenas como apoio.</p></div><label className="search"><Search size={17}/><input aria-label="Buscar motorista" placeholder="Nome, CPF, telefone ou placa" value={search} onChange={event=>setSearch(event.target.value)}/></label></section>
    {error&&<div className="error-banner">{error}</div>}
    <section className="history-layout"><div className="panel history-drivers"><header><strong>{total} motorista(s)</strong></header>{drivers.map(driver=><button key={driver.id} className={selected?.id===driver.id?'active':''} onClick={()=>setSelected(driver)}><UserRound size={19}/><span><strong>{driver.name}</strong><small>{driver.id} · {driver.total_trips} viagem(ns)</small></span><i>{driver.pending_evaluations||0} pendente(s)</i></button>)}{!drivers.length&&!error&&<p className="history-empty">Nenhum motorista consolidado até o momento</p>}{total>pageSize&&<footer className="history-pagination"><button className="secondary-button" disabled={page===1} onClick={()=>setPage(value=>Math.max(1,value-1))}>Anterior</button><span>Página {page} de {totalPages}</span><button className="secondary-button" disabled={page>=totalPages} onClick={()=>setPage(value=>Math.min(totalPages,value+1))}>Próxima</button></footer>}</div>
    <div className="page-stack">{profile?<><section className="panel history-profile"><div><span className="eyebrow">Perfil operacional</span><h2>{profile.name}</h2><p>{profile.cpf_masked||profile.id} · {profile.identity_status==='PENDING'?'Identidade pendente':'Identidade verificada'}</p></div><div className="history-kpis"><article><span>Viagens</span><strong>{profile.total_trips}</strong></article><article><span>Finalizadas</span><strong>{profile.finished_trips||0}</strong></article><article><span>Pendentes</span><strong>{profile.pending_evaluations||0}</strong></article><article><span>Pontualidade considerada</span><strong>{profile.considered_punctuality_percent??'—'}{profile.considered_punctuality_percent!=null?'%':''}</strong></article></div></section>
    <section className="panel history-trips"><div className="history-filters"><input aria-label="Início" type="date" value={start} onChange={e=>setStart(e.target.value)}/><input aria-label="Fim" type="date" value={end} onChange={e=>setEnd(e.target.value)}/><select aria-label="Rota" value={route} onChange={e=>setRoute(e.target.value)}><option value="">Todas as rotas</option>{profile.routes.map(item=><option key={item.route_name} value={item.route_name}>{item.route_name}</option>)}</select><input aria-label="Cliente" placeholder="Cliente" value={customer} onChange={e=>setCustomer(e.target.value)}/><select aria-label="Status" value={status} onChange={e=>setStatus(e.target.value)}><option value="">Todos os status</option><option value="FINALIZADA_NO_SISTEMA">Finalizada</option><option value="EM_VIAGEM">Em andamento</option><option value="CANCELADA">Cancelada</option></select><button className="primary-button" type="button" disabled={reportLoading} onClick={downloadReport}><Download size={15}/>{reportLoading?'Gerando PDF…':'Baixar relatório em PDF'}</button></div><div className="history-table"><div className="history-row head"><span>Viagem/data</span><span>Rota</span><span>Placa/cliente</span><span>Status</span><span>Pontualidade</span><span>Avaliação</span></div>{trips.map(trip=><div className="history-row" key={trip.trip_key}><span><strong>{trip.provider_trip_id||trip.trip_key}</strong><small>{formatDate(referenceDate(trip))}</small></span><span>{trip.route_name||`${trip.origin_name||'Não informado'} → ${trip.destination_name||'Não informado'}`}</span><span><strong>{trip.plate}</strong><small>{trip.customer||'Cliente não informado'}</small></span><span>{trip.status}</span><span>{punctualityLabel(trip.considered_punctuality||trip.automatic_punctuality)}</span><span>{trip.evaluation_status}</span></div>)}</div></section></>:<section className="panel history-empty">Selecione um motorista para consultar o histórico.</section>}</div></section>
  </div>
}
function formatDate(value?:string|null){return value?new Date(value).toLocaleString('pt-BR'):'Data não informada'}
function referenceDate(trip:DriverHistoryTrip){return trip.loaded_at||trip.started_at||trip.arrived_destination_at||trip.finished_at||trip.source_created_at}
function punctualityLabel(value?:string|null){return !value||value==='UNAVAILABLE'?'Não disponível':value}
