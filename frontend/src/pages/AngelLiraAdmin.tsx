import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Database, MapPinned, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import type { AngelLiraReviewItem } from '../types'

export function AngelLiraAdmin() {
  const query=useQuery({queryKey:['angellira','admin'],queryFn:api.angelLiraAdmin,staleTime:10*60*1000})
  if(query.isLoading)return <section className="panel angellira-state"><Database size={24}/><h2>Carregando base AngelLira...</h2></section>
  if(query.isError||!query.data)return <section className="panel angellira-state angellira-state--error"><AlertTriangle size={24}/><h2>Base AngelLira indisponível</h2><p>{query.error?.message||'Não foi possível carregar a fila administrativa.'}</p><button className="secondary-button" onClick={()=>query.refetch()}>Tentar novamente</button></section>
  const value=query.data
  const dataset=value.status.dataset
  const stationQueue=[...value.review_queue.stations,...value.review_queue.variants]
  const stationStatus=value.status.stations.by_status
  return <div className="page-stack angellira-admin">
    <section className="panel angellira-heading"><div><span className="eyebrow">Base operacional de referência</span><h2>AngelLira</h2><p>{dataset?.dataset_id||'Dataset ainda não importado'} · fonte {dataset?.source_name||'AngelLira'} · versão {dataset?.source_version||'não informada'}</p></div><span className="reference-badge"><ShieldCheck size={15}/>Somente leitura</span></section>
    <section className="angellira-metrics">
      <Metric label="Postos importados" value={value.status.stations.total}/>
      <Metric label="Validados no mapa" value={value.status.stations.visible}/>
      <Metric label="Postos em revisão" value={(stationStatus.pending_review||0)+(stationStatus.probable||0)+(stationStatus.not_geocoded||0)}/>
      <Metric label="Áreas sem geometria" value={value.status.risk_areas.total-value.status.risk_areas.validated_geometries}/>
    </section>
    <section className="panel reference-notice"><MapPinned size={20}/><div><strong>Uso operacional seguro</strong><p>Postos homologados são referências visuais e não geram alertas nem alteram Normal, Atenção ou Crítica. Somente coordenadas validadas aparecem no mapa.</p></div></section>
    <section className="panel angellira-queue">
      <header><div><span className="eyebrow">Validação conservadora</span><h2>Postos e variantes pendentes</h2></div><span className="count-pill">{stationQueue.length}</span></header>
      <ReviewList items={stationQueue} empty="Nenhum posto pendente de revisão."/>
    </section>
    <section className="panel angellira-queue">
      <header><div><span className="eyebrow">Geometria futura</span><h2>Áreas estimadas de risco</h2></div><span className="count-pill">{value.review_queue.risk_areas.length}</span></header>
      <div className="risk-language"><AlertTriangle size={17}/><span>Área estimada pela AngelLira - não representa ocorrência confirmada.</span></div>
      <p className="queue-help">Nenhuma referência sem Polygon ou MultiPolygon WGS84 validado é exibida no mapa ou habilitada para permanência.</p>
      <ReviewList items={value.review_queue.risk_areas} empty="Nenhuma área pendente."/>
    </section>
  </div>
}

function Metric({label,value}:{label:string;value:number}){return <article className="panel"><span>{label}</span><strong>{value}</strong></article>}
function ReviewList({items,empty}:{items:AngelLiraReviewItem[];empty:string}) {
  if(!items.length)return <p className="table-empty">{empty}</p>
  return <div className="reference-list">{items.map((item,index)=>{const name=item.name||item.canonical_name||item.representative_name||'Registro sem nome';const id=item.id||item.post_id||item.risk_area_id||item.exact_group_id||String(index);const status=item.status||item.map_validation_status||item.geometry_validation_status||'pending_review';const reason=item.reason||item.data_quality_reason||item.candidate_reason||'Aguardando revisão responsável.';return <article key={`${item.kind||'review'}:${id}`}><div><strong>{name}</strong><span>{[item.city,item.uf].filter(Boolean).join('/')||'Localidade não informada'}{item.road?` · ${item.road}`:''}</span></div><div><em>{statusLabel(status)}</em><small>{reason}</small></div></article>})}</div>
}
function statusLabel(value:string){return {probable:'Provável',pending_review:'Revisão pendente',not_geocoded:'Não geocodificado',not_available:'Geometria indisponível',rejected:'Rejeitado'}[value]||value.replaceAll('_',' ')}
