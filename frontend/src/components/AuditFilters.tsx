import {CalendarDays,Filter,RotateCcw,Search,Truck,UserRound} from 'lucide-react'
import {type FormEvent,useState} from 'react'
import './AuditFilters.css'

export interface AuditFilterValues{actor_query?:string;action_type?:string;trip_key?:string;date_from?:string}
interface Props{onApply:(filters:AuditFilterValues)=>void;isLoading?:boolean}
const empty={actor_query:'',action_type:'',trip_key:'',date_from:''}
const actions=[
 ['','Todas as ações'],['AUTH_LOGIN_SUCCESS','Login realizado'],['AUTH_LOGIN_FAILURE','Falha de login'],['AUTH_LOGOUT','Logout'],
 ['USER_CREATED','Usuário criado'],['USER_UPDATED','Usuário atualizado'],['USER_ACTIVATED','Usuário ativado'],['USER_DEACTIVATED','Usuário inativado'],['USER_ROLE_CHANGED','Perfil alterado'],['USER_PASSWORD_RESET','Senha redefinida'],['USER_DELETED','Usuário excluído'],
 ['TRIP_PLAN_UPDATED','Programação alterada'],['TRIP_FINALIZED','Viagem finalizada'],['TRIP_REOPENED','Viagem reaberta'],['TRIP_STATUS_CORRECTED','Status da viagem corrigido'],['TRIP_ROUTE_ASSIGNED','Rota atribuída'],['TRIP_DRIVER_ASSIGNED','Motorista atribuído'],['TRIP_RETURN_DECISION','Decisão de retorno'],['TRIP_CANCELLED','Viagem cancelada'],['TRIP_ARCHIVED','Viagem arquivada'],['TRIP_UNARCHIVED','Viagem desarquivada'],
 ['STOP_JUSTIFIED','Parada justificada'],['OBSERVATION_CREATED','Observação criada'],['OBSERVATION_CORRECTED','Observação corrigida'],['OBSERVATION_VOIDED','Observação anulada'],
 ['INCIDENT_CREATED','Incidente criado'],['INCIDENT_UPDATED','Incidente atualizado'],['INCIDENT_CONFIRMED','Incidente confirmado'],['INCIDENT_CLOSED','Incidente encerrado'],['INCIDENT_DISCARDED','Incidente descartado'],
 ['PUBLIC_LINK_CREATED','Link público criado'],['PUBLIC_LINK_REVOKED','Link público revogado'],['REPORT_GENERATED','Relatório gerado'],['INTEGRATION_INVOKED','Integração executada'],
]

export function AuditFilters({onApply,isLoading}:Props){
 const [values,setValues]=useState(empty)
 const update=(key:keyof typeof values,value:string)=>setValues(current=>({...current,[key]:value}))
 const submit=(event:FormEvent)=>{event.preventDefault();const result=Object.fromEntries(Object.entries(values).flatMap(([key,raw])=>{const value=raw.trim();if(!value)return[];return[[key,key==='date_from'?new Date(value).toISOString():value]]})) as AuditFilterValues;onApply(result)}
 const clear=()=>{setValues(empty);onApply({})}
 return <form className="audit-filters" onSubmit={submit}><div className="filters-grid"><label className="filter-group" htmlFor="audit-user"><span>Usuário</span><span className="audit-input"><UserRound/><input id="audit-user" value={values.actor_query} onChange={e=>update('actor_query',e.target.value)} placeholder="Nome ou usuário"/></span></label><label className="filter-group" htmlFor="audit-action"><span>Ação</span><span className="audit-input"><Filter/><select id="audit-action" value={values.action_type} onChange={e=>update('action_type',e.target.value)}>{actions.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></span></label><label className="filter-group" htmlFor="audit-trip"><span>Viagem</span><span className="audit-input"><Truck/><input id="audit-trip" value={values.trip_key} onChange={e=>update('trip_key',e.target.value)} placeholder="Chave exata da viagem"/></span></label><label className="filter-group" htmlFor="audit-since"><span>Desde</span><span className="audit-input"><CalendarDays/><input id="audit-since" type="datetime-local" value={values.date_from} onChange={e=>update('date_from',e.target.value)}/></span></label></div><div className="audit-filter-actions"><button className="btn-clear-filters" type="button" onClick={clear}><RotateCcw/>Limpar</button><button className="btn-apply-filters" type="submit" disabled={isLoading}><Search/>{isLoading?'Buscando...':'Aplicar filtros'}</button></div></form>
}
