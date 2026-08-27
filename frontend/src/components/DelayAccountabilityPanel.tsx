import { useQuery } from '@tanstack/react-query'
import { ClipboardList } from 'lucide-react'
import { api } from '../api'
import { usePermission } from '../permissions'

const labels:Record<string,string>={DRIVER:'Motorista',CUSTOMER_CD:'Cliente / CD',INTERNAL_TEAM:'Time interno',CARRIER:'Transportadora',TRAFFIC_WEATHER:'Trânsito / clima',UNDETERMINED:'Não determinada'}

export function DelayAccountabilityPanel(){
 const allowed=usePermission('audit:read-operational')
 const query=useQuery({queryKey:['delay-accountability'],queryFn:()=>api.delayAccountability(),enabled:allowed})
 if(!allowed)return null
 const data=query.data
 return <details className="panel delay-accountability"><summary><ClipboardList size={18}/><span><strong>Responsabilidade pelos atrasos</strong><small>{data?`${data.total} registro(s) auditável(is)`:'Carregando registros...'}</small></span></summary><div className="delay-accountability__content"><div className="delay-accountability__counts">{Object.entries(data?.counts_by_responsibility||{}).map(([key,value])=><span key={key}><b>{value}</b>{labels[key]||key}</span>)}</div>{data?.items.slice(0,50).map(item=><article key={item.id}><div><strong>{item.driver||'Motorista não informado'} · {item.plate}</strong><small>{new Date(item.occurred_at).toLocaleString('pt-BR')} · {labels[item.metadata?.responsibility||'']||item.metadata?.responsibility}</small></div><p>{item.content}</p></article>)}{data&&!data.items.length&&<p>Nenhum atraso com responsabilidade atribuída.</p>}</div></details>
}
