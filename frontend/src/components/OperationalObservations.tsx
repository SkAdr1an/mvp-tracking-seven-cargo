import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { usePanelSession, usePermission } from '../permissions'
import type { OperationalObservation } from '../types'

const types={GENERAL:'Geral',STOP:'Parada',DRIVER_CONTACT:'Contato com motorista',GR_INTERVENTION:'Intervenção GR',INCIDENT:'Incidente',OPERATIONAL_NOTE:'Nota operacional'}
const responsibilities:Record<string,string>={DRIVER:'Motorista',CUSTOMER_CD:'Cliente / CD',INTERNAL_TEAM:'Time interno',CARRIER:'Transportadora',TRAFFIC_WEATHER:'Trânsito / clima',UNDETERMINED:'Ainda não determinada'}

export function OperationalObservations({tripKey,stops}:{tripKey:string;stops:{id:number;started_at?:string|null}[]}){
 const client=useQueryClient(),session=usePanelSession(),canCreate=usePermission('observations:create'),canCorrect=usePermission('observations:correct-own'),canVoid=usePermission('observations:void-any')
 const query=useQuery({queryKey:['observations',tripKey],queryFn:()=>api.observations(tripKey)})
 const [open,setOpen]=useState(false),[error,setError]=useState('')
 const [form,setForm]=useState({observation_type:'GENERAL',content:'',occurred_at:localNow(),include_in_report:true,stop_id:'',delay_category:'',responsibility:'',critical_impact:false})
 const refresh=()=>client.invalidateQueries({queryKey:['observations',tripKey]})
 const create=useMutation({mutationFn:()=>api.createObservation(tripKey,{...form,delay_category:form.delay_category||null,responsibility:form.responsibility||null,occurred_at:new Date(form.occurred_at).toISOString(),stop_id:form.observation_type==='STOP'&&form.stop_id?Number(form.stop_id):null}),onSuccess:()=>{void refresh();setOpen(false);setForm({...form,content:'',occurred_at:localNow()})},onError:e=>setError(e.message)})
 const correct=(item:OperationalObservation)=>{const content=window.prompt('Novo conteúdo',item.content),reason=window.prompt('Motivo da correção');if(content&&reason)api.correctObservation(item.id,{content,reason}).then(refresh).catch(e=>setError(e.message))}
 const voidItem=(item:OperationalObservation)=>{const reason=window.prompt('Motivo do encerramento ou anulação');if(reason)api.voidObservation(item.id,reason).then(refresh).catch(e=>setError(e.message))}
 return <section className="operation-history observations"><h3>Observações operacionais</h3>{canCreate&&<button onClick={()=>setOpen(!open)}>Adicionar observação</button>}{open&&<form onSubmit={e=>{e.preventDefault();setError('');create.mutate()}}>
  <label>Tipo<select value={form.observation_type} onChange={e=>setForm({...form,observation_type:e.target.value})}>{Object.entries(types).filter(([value])=>value!=='STOP'||stops.length>0).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
  <label>Conteúdo<textarea value={form.content} onChange={e=>setForm({...form,content:e.target.value})} maxLength={4000} required/></label>
  <label>Horário<input type="datetime-local" value={form.occurred_at} onChange={e=>setForm({...form,occurred_at:e.target.value})} required/></label>
  {form.observation_type==='STOP'&&stops.length>0&&<label>Parada<select value={form.stop_id} onChange={e=>setForm({...form,stop_id:e.target.value})} required><option value="">Selecione</option>{stops.map(stop=><option key={stop.id} value={stop.id}>Parada {stop.id}{stop.started_at?` · ${new Date(stop.started_at).toLocaleString('pt-BR')}`:''}</option>)}</select></label>}
  <label>Motivo do atraso<select value={form.delay_category} onChange={e=>setForm({...form,delay_category:e.target.value,responsibility:e.target.value?form.responsibility||'UNDETERMINED':''})}><option value="">Não se aplica</option><option value="INVOICE">Emissão de nota</option><option value="QUEUE">Fila no CD</option><option value="LOADING">Carregamento</option><option value="RELEASE">Liberação</option><option value="SYSTEM">Sistema</option><option value="OTHER">Outro</option></select></label>
  {form.delay_category&&<><label>Responsabilidade<select value={form.responsibility} onChange={e=>setForm({...form,responsibility:e.target.value})}>{Object.entries(responsibilities).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label><input type="checkbox" checked={form.critical_impact} onChange={e=>setForm({...form,critical_impact:e.target.checked})}/> Manter como impacto crítico operacional</label></>}
  <label><input type="checkbox" checked={form.include_in_report} onChange={e=>setForm({...form,include_in_report:e.target.checked})}/> Incluir no relatório</label><button disabled={create.isPending}>Registrar</button>
 </form>}{error&&<div className="form-error">{error}</div>}{query.data?.observations.map(item=><article key={item.id} className={`observation-item observation-item--${item.status.toLowerCase()}`}><small>{new Date(item.occurred_at).toLocaleString('pt-BR')} · {item.type_label} · {item.status}</small><p>{item.content}</p>{item.metadata?.responsibility&&<b>Responsabilidade: {responsibilities[item.metadata.responsibility]||item.metadata.responsibility}</b>}<span>Registrado por: {item.author.display_name} — {item.author.role_label}</span><div>{canCorrect&&item.status==='ACTIVE'&&item.author.user_id===session?.user_id&&<button onClick={()=>correct(item)}>Corrigir</button>}{canVoid&&item.status==='ACTIVE'&&<button onClick={()=>voidItem(item)}>Encerrar / anular</button>}</div></article>)}</section>
}
function localNow(){const date=new Date(Date.now()-new Date().getTimezoneOffset()*60000);return date.toISOString().slice(0,16)}
