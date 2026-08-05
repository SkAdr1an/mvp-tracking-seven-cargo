import { AlertTriangle, Clock3, CloudRain, Database, Gauge, MapPinned, Route, ShieldCheck, TrafficCone, X } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Driver } from '../types'
import { formatAgo } from '../utils'
import { operationalAvailability, progressLabel } from '../driverPresentation'
import { validDate } from '../dataSafety'

export function DriverDiagnostic({ driver, onClose }: { driver: Driver; onClose: () => void }) {
  const value = driver.diagnostic
  const availability = operationalAvailability(driver)
  const progress = driver.route_progress
  const operation = driver.operational
  if (!value) return <section className="panel driver-diagnostic driver-diagnostic--empty" data-diagnostic-code={availability?.code||'ETA_UNAVAILABLE'}>
    <button className="diagnostic-close" onClick={onClose} aria-label="Fechar diagnóstico"><X size={18}/></button>
    <ShieldCheck size={28}/><h2>{availability?.message||'Sem ETA operacional'}</h2>
    <p>{availability?'Os demais dados válidos da viagem continuam disponíveis na lista e no mapa.':'A viagem está encerrada, aguarda confirmação de retorno ou ainda não possui dados confiáveis suficientes.'}</p>
  </section>
  const route = operation?.route
  const direction = operation?.state === 'RETORNO_SEVEN_CONFIRMADO' ? 'Retorno confirmado' : 'Ida'
  return <section className="panel driver-diagnostic" aria-label="Diagnóstico operacional individual">
    <header className="diagnostic-header">
      <div className="diagnostic-identity"><span className="eyebrow">Diagnóstico operacional</span><h2>{driver.driver||'Motorista não informado'}</h2><p className="diagnostic-identity__vehicle">{driver.id}{driver.trailer_plate?` · ${driver.trailer_plate}`:''}</p><p className="diagnostic-identity__route">{route?.name||driver.route||'Rota não informada'} · {direction}</p><p>Atualizado {formatAgo(value.calculated_at)}</p></div>
      <div className="diagnostic-header__status"><Classification value={value.classification}/><button className="diagnostic-close" onClick={onClose} aria-label="Fechar diagnóstico"><X size={18}/></button></div>
    </header>
    <div className="diagnostic-explanation"><AlertTriangle size={18}/><strong>{value.status_explanation}</strong></div>
    {availability&&<div className="diagnostic-explanation" data-diagnostic-code={availability.code}><AlertTriangle size={18}/><strong>{availability.message}</strong></div>}
    <div className="diagnostic-kpis">
      <Kpi label="ETA mais provável" value={date(value.eta_at)} icon={Clock3}/>
      <Kpi label="Janela estimada" value={`${date(value.window_start_at)} — ${date(value.window_end_at)}`} icon={Clock3}/>
      <Kpi label="Compromisso do cliente" value={date(value.client_eta_at)} icon={MapPinned}/>
      <Kpi label="Diferença para o compromisso" value={commitment(value.commitment_delta_minutes)} icon={Clock3}/>
      <Kpi label="Tendência" value={trend(value.trend)} icon={Gauge}/>
      <Kpi label="Confiança" value={confidence(value.confidence)} icon={ShieldCheck}/>
      <Kpi label="Quilômetros restantes" value={progress?.remaining_distance_km != null ? `${Math.round(progress.remaining_distance_km)} km` : 'Indisponível'} icon={Route}/>
    </div>
    <div className="diagnostic-columns diagnostic-columns--primary">
      <DiagnosticSection title="Viagem e posição">
        <Fact label="Origem" value={route?.origin_name || 'Não informada'}/>
        <Fact label="Destino" value={route?.destination_name || driver.route || 'Não informado'}/>
        <Fact label="Sentido" value={direction}/>
        <Fact label="Progresso" value={progressLabel(driver)}/>
        <Fact label="Última posição" value={driver.last_update ? `${formatAgo(driver.last_update)} · ${driver.location_description || 'Local não descrito'}` : 'Indisponível'}/>
        <Fact label="Velocidade" value={driver.stale ? 'Desatualizada' : driver.location?.speed_kmh != null ? `${Math.round(driver.location.speed_kmh)} km/h` : 'Não informada'}/>
        <Fact label="Tempo parado" value={value.stopped_minutes ? `${Math.round(value.stopped_minutes)} min` : 'Sem parada prolongada detectada'}/>
        <Fact label="Rota oficial" value={progress?.route_state === 'OUTSIDE' ? `Fora da rota${progress.return_distance_km != null ? ` · retorno aproximado ${progress.return_distance_km} km` : ''}` : progress?.route_state === 'STALE' ? 'Posição desatualizada' : 'Compatível'}/>
      </DiagnosticSection>
      <DiagnosticSection title="Riscos à frente">
        {!Array.isArray(value.risks) || !value.risks.length ? <Empty text="Nenhum risco relevante identificado."/> : null}
        {(Array.isArray(value.risks) ? value.risks : []).map((risk,index)=><article className="diagnostic-risk" key={`${risk.type}-${index}`}>{risk.type === 'WEATHER' ? <CloudRain size={16}/> : risk.type === 'TRAFFIC' ? <TrafficCone size={16}/> : <AlertTriangle size={16}/>}<div><strong>{risk.description || 'Risco sem descrição'}</strong><small>{risk.delay_minutes ? `Impacto considerado: ${Math.round(risk.delay_minutes)} min` : risk.return_distance_km ? `Retorno à rota: ${risk.return_distance_km} km` : 'Monitoramento operacional'}</small></div></article>)}
      </DiagnosticSection>
    </div>
    {value.angellira_context&&<ResponsiveDetails title="Referências AngelLira"><DiagnosticSection title="Referências AngelLira" wide>
      <div className="reference-context">
        <Database size={17}/>
        <div>
          <strong>{value.angellira_context.source_name} · versão {value.angellira_context.source_version}</strong>
          {value.angellira_context.nearby_station&&<p>Posto homologado próximo: {value.angellira_context.nearby_station.canonical_name} · {value.angellira_context.nearby_station.city}/{value.angellira_context.nearby_station.uf}{value.angellira_context.nearby_station.distance_m!=null?` · ${Math.round(value.angellira_context.nearby_station.distance_m)} m`:''}. Referência visual; não gera alerta.</p>}
          {value.angellira_context.risk_area&&<p>{value.angellira_context.risk_area.message}</p>}
          {value.angellira_context.conflict_resolution&&<small>{value.angellira_context.conflict_resolution}</small>}
        </div>
      </div>
    </DiagnosticSection></ResponsiveDetails>}
    <ResponsiveDetails title="Cenários de chegada"><DiagnosticSection title="Cenários de chegada" wide>
      {value.scenarios?.optimistic && value.scenarios?.likely && value.scenarios?.conservative
        ? <div className="scenario-grid"><Scenario title="Otimista" data={value.scenarios.optimistic}/><Scenario title="Mais provável" data={value.scenarios.likely}/><Scenario title="Conservador" data={value.scenarios.conservative}/></div>
        : <Empty text="Cenários de chegada indisponíveis para este registro."/>}
    </DiagnosticSection></ResponsiveDetails>
    <ResponsiveDetails title="Informações complementares"><div className="diagnostic-columns">
      <DiagnosticSection title="Confiança do cálculo">
        {(Array.isArray(value.confidence_reasons) ? value.confidence_reasons : []).map((reason)=><p className="diagnostic-line" key={reason}>{reason}</p>)}
        {!Array.isArray(value.confidence_reasons) || !value.confidence_reasons.length ? <Empty text="Motivos de confiança indisponíveis."/> : null}
      </DiagnosticSection>
      <DiagnosticSection title="Ações recomendadas">
        {(Array.isArray(value.recommendations) ? value.recommendations : []).map((item)=><p className="diagnostic-line diagnostic-line--action" key={item}>{item}</p>)}
        {!Array.isArray(value.recommendations) || !value.recommendations.length ? <Empty text="Sem recomendação disponível."/> : null}
      </DiagnosticSection>
    </div></ResponsiveDetails>
    <footer>Último recálculo: {date(value.calculated_at)} · Método {value.method_version}</footer>
  </section>
}

function DiagnosticSection({ title, children, wide=false }: { title:string;children:ReactNode;wide?:boolean }) { return <section className={`diagnostic-section ${wide?'diagnostic-section--wide':''}`}><h3>{title}</h3>{children}</section> }
function ResponsiveDetails({title,children}:{title:string;children:ReactNode}){return <details className="diagnostic-details" open><summary>{title}</summary><div className="diagnostic-details__content">{children}</div></details>}
function Kpi({label,value,icon:Icon}:{label:string;value:string;icon:typeof Clock3}){return <div><Icon size={16}/><span>{label}</span><strong>{value}</strong></div>}
function Fact({label,value}:{label:string;value:string}){return <div className="diagnostic-fact"><span>{label}</span><strong>{value}</strong></div>}
function Scenario({title,data}:{title:string;data:{eta_at:string;explanation:string}}){return <article><span>{title}</span><strong>{date(data.eta_at)}</strong><p>{data.explanation}</p></article>}
function Empty({text}:{text:string}){return <p className="diagnostic-empty">{text}</p>}
function date(value?:string|null){const safe=validDate(value);return safe?new Date(safe).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'Não informado'}
function trend(value:string){return {ADIANTADO:'Adiantado',DENTRO_DO_PRAZO:'Dentro do prazo',RISCO_DE_ATRASO:'Risco de atraso',PROVAVEL_ATRASO:'Provável atraso',SEM_COMPROMISSO:'Sem compromisso cadastrado'}[value]||value}
function confidence(value:string){return {HIGH:'Alta',MEDIUM:'Média',LOW:'Baixa'}[value]||value}
function commitment(value?:number|null){if(value==null)return 'Não calculada';return value>0?`${Math.round(value)} min de atraso`:`${Math.abs(Math.round(value))} min de margem`}
function Classification({value}:{value?:string|null}){return <em className={`trip-class trip-class--${value?.toLowerCase()||'unknown'}`}>{value==='ATENCAO'?'ATENÇÃO':value==='CRITICA'?'CRÍTICA':value||'SEM ETA'}</em>}
