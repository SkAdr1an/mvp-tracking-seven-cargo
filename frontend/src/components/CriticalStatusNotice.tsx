import { AlertTriangle, Clock3 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import type { Driver } from '../types'
import { api } from '../api'

export function CriticalStatusNotice({driver}:{driver:Driver}) {
  const tripKey=driver.operational?.trip_key
  const observations=useQuery({queryKey:['observations',tripKey],queryFn:()=>api.observations(tripKey!),enabled:driver.prediction?.classification==='CRITICA'&&Boolean(tripKey)})
  if (driver.prediction?.classification !== 'CRITICA') return null
  const diagnostic = driver.diagnostic
  const delay = diagnostic?.commitment_delta_minutes ?? driver.prediction.delay_minutes
  const eta = diagnostic?.eta_at ?? driver.prediction.eta_at
  const sla = diagnostic?.client_eta_at ?? driver.prediction.sla_at
  const causes = (diagnostic?.risks || []).map((risk)=>risk.description).filter(Boolean).slice(0,3)
  const attributed=observations.data?.observations.find((item)=>item.status==='ACTIVE'&&item.metadata?.responsibility)
  const reason = delay != null && delay > 0
    ? `A chegada mais provável está ${Math.round(delay)} minutos após o compromisso do cliente.`
    : sla
      ? 'O compromisso de chegada já foi ultrapassado.'
      : diagnostic?.status_explanation || 'A previsão operacional atual classificou esta viagem como crítica.'

  return <aside className="critical-status-notice" role="status" aria-label="Motivo da classificação crítica">
    <AlertTriangle size={20}/>
    <div>
      <strong>Por que esta viagem está crítica?</strong>
      <p>{reason}</p>
      {(eta||sla)&&<div className="critical-status-notice__times"><Clock3 size={13}/>{sla&&<span>Compromisso: {dateTime(sla)}</span>}{eta&&<span>Chegada prevista: {dateTime(eta)}</span>}</div>}
      {causes.length>0&&<small>Fatores considerados: {causes.join(' · ')}</small>}
      {attributed&&<div className="critical-status-notice__attribution"><b>Atraso justificado: {attributed.content}</b><span>Responsabilidade: {responsibility(attributed.metadata!.responsibility!)} · registrado por {attributed.author.display_name}</span></div>}
    </div>
  </aside>
}

function dateTime(value:string){return new Date(value).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}
function responsibility(value:string){return {DRIVER:'Motorista',CUSTOMER_CD:'Cliente / CD',INTERNAL_TEAM:'Time interno',CARRIER:'Transportadora',TRAFFIC_WEATHER:'Trânsito / clima',UNDETERMINED:'Ainda não determinada'}[value]||value}
