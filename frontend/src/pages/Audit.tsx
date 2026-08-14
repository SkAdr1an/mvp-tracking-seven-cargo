import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import type { AuditEvent } from '../types'

export function Audit() {
  const [filters,setFilters]=useState({actor_user_id:'',action_type:'',trip_key:'',date_from:''})
  const query=useQuery({queryKey:['audit',filters],queryFn:()=>api.audit(Object.fromEntries(Object.entries(filters).filter(([,value])=>value)))})
  const [selected,setSelected]=useState<AuditEvent|null>(null)
  return <section className="panel audit-page">
    <div className="page-heading"><div><span className="eyebrow">Rastreabilidade</span><h2>Auditoria</h2></div></div>
    <div className="audit-filters">
      <label>Usuário<input value={filters.actor_user_id} onChange={e=>setFilters({...filters,actor_user_id:e.target.value})}/></label>
      <label>Ação<input value={filters.action_type} onChange={e=>setFilters({...filters,action_type:e.target.value.toUpperCase()})}/></label>
      <label>Viagem<input value={filters.trip_key} onChange={e=>setFilters({...filters,trip_key:e.target.value})}/></label>
      <label>Desde<input type="datetime-local" value={filters.date_from} onChange={e=>setFilters({...filters,date_from:e.target.value})}/></label>
    </div>
    {query.isLoading&&<p>Carregando eventos...</p>}{query.error&&<div className="form-error">Não foi possível carregar a auditoria.</div>}
    <div className="table-wrap"><table><thead><tr><th>Data/hora</th><th>Usuário</th><th>Perfil</th><th>Ação</th><th>Recurso</th><th>Viagem</th><th>Resumo</th></tr></thead>
      <tbody>{query.data?.events.map(event=><tr key={event.id} onClick={()=>setSelected(event)} tabIndex={0}>
        <td>{dateLabel(event.occurred_at)}</td><td>{event.actor_display_name_snapshot}</td><td>{event.actor_role_snapshot}</td><td>{label(event.action_type)}</td><td>{event.resource_type}{event.resource_id?` · ${event.resource_id}`:''}</td><td>{event.trip_key||'—'}</td><td>{event.justification||event.content||label(event.action_type)}</td>
      </tr>)}</tbody></table></div>
    {selected&&<div className="audit-detail"><button onClick={()=>setSelected(null)}>Fechar</button><h3>{label(selected.action_type)}</h3><p>{dateLabel(selected.occurred_at)} · {selected.actor_display_name_snapshot} ({selected.actor_role_snapshot})</p>{selected.justification&&<p><strong>Justificativa:</strong> {selected.justification}</p>}<SafeDetails title="Antes" value={selected.before}/><SafeDetails title="Depois" value={selected.after}/><SafeDetails title="Metadados" value={selected.metadata}/></div>}
  </section>
}

function SafeDetails({title,value}:{title:string;value?:Record<string,unknown>|null}){return value&&Object.keys(value).length?<details><summary>{title}</summary><pre>{JSON.stringify(value,null,2)}</pre></details>:null}
function label(value:string){return value.toLowerCase().replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase())}
function dateLabel(value:string){return new Date(value).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'})}
