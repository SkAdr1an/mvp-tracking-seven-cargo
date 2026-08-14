import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { AlertTriangle, Archive, ArchiveRestore, CheckCircle2, Clock3, Download, History, MapPinned, Pencil, RotateCcw, Route, XCircle } from 'lucide-react'
import { api } from '../api'
import type { AuditEvent, OperationalState, OperationalTrip } from '../types'
import { OperationalActionDialog, type OperationalDialogField } from './OperationalActionDialog'
import { DriverPublicLink } from './DriverPublicLink'
import { OperationalObservations } from './OperationalObservations'
import { usePermission } from '../permissions'
import '../mobile-map.css'

type DialogState =
  | { kind: 'action'; action: 'finalize' | 'reopen' | 'undo_detection' }
  | { kind: 'correct' }
  | { kind: 'return'; decision: 'YES' | 'NO' | 'LATER' }
  | { kind: 'lifecycle'; action: 'cancel' | 'archive' | 'unarchive' }

const labels: Record<OperationalState, string> = {
  PROGRAMADA: 'Programada', NA_ORIGEM: 'Na origem', EM_CARREGAMENTO: 'Em carregamento',
  EM_VIAGEM: 'Em viagem', NO_DESTINO: 'No destino',
  FINALIZADA_NO_SISTEMA: 'Finalizada no sistema', REABERTA_MANUALMENTE: 'Reaberta manualmente',
  RETORNO_SEVEN_CONFIRMADO: 'Retorno Seven confirmado', RETORNO_CONCLUIDO: 'Retorno concluído',
  CANCELADA: 'Cancelada',
}

export function OperationalTripPanel({ initial }: { initial: OperationalTrip }) {
  const canReport=usePermission('reports:generate'),canCorrectStatus=usePermission('trips:status-correct'),canFinalize=usePermission('trips:finalize'),canReopen=usePermission('trips:reopen'),canPublicLink=usePermission('public-links:manage'),canEdit=usePermission('trips:edit'),canCancel=usePermission('trips:cancel'),canArchive=usePermission('trips:archive')
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<DialogState | null>(null)
  const [feedback, setFeedback] = useState('')
  const [reportPending, setReportPending] = useState(false)
  const [reportError, setReportError] = useState('')
  const detail = useQuery({
    queryKey: ['operational-trip', initial.trip_key],
    queryFn: () => api.operationalTrip(initial.trip_key),
    initialData: initial.events ? initial : undefined,
    refetchInterval: 60_000,
  })
  const trip = detail.data || initial
  const canAudit=usePermission('audit:read-operational')
  const audit=useQuery({queryKey:['trip-audit',initial.trip_key],queryFn:()=>api.tripAudit(initial.trip_key),enabled:canAudit})
  const action = useMutation({
    mutationFn: (input: Parameters<typeof api.operationalAction>[1]) => api.operationalAction(initial.trip_key, input),
    onSuccess: (data) => {
      queryClient.setQueryData(['operational-trip', initial.trip_key], data)
      setDialog(null)
      setFeedback('Ação registrada com sucesso no histórico operacional.')
    },
  })
  const returnDecision = useMutation({
    mutationFn: (input: Parameters<typeof api.returnDecision>[1]) => api.returnDecision(trip.return_candidate!.id, input),
    onSuccess: (data) => {
      queryClient.setQueryData(['operational-trip', initial.trip_key], data)
      void queryClient.invalidateQueries({ queryKey: ['fleet'] })
      setDialog(null)
      setFeedback('Decisão de retorno registrada com sucesso.')
    },
  })
  const lifecycle = useMutation({
    mutationFn: (input: {action:'cancel'|'archive'|'unarchive';reason:string}) => api.tripLifecycle(initial.trip_key,input.action,input.reason),
    onSuccess: (data) => {
      queryClient.setQueryData(['operational-trip', initial.trip_key], data)
      void queryClient.invalidateQueries({ queryKey: ['fleet'] })
      setDialog(null); setFeedback('Ação registrada com sucesso no histórico operacional.')
    },
  })
  const open = (next: DialogState) => { setFeedback(''); action.reset(); returnDecision.reset(); lifecycle.reset(); setDialog(next) }
  const confirm = (values: Record<string, string>) => {
    if (!dialog) return
    if (dialog.kind === 'action') action.mutate({ action: dialog.action, justification: values.justification })
    if (dialog.kind === 'correct') action.mutate({ action: 'correct_times', justification: values.justification, corrections: { [values.field]: new Date(values.value).toISOString() } })
    if (dialog.kind === 'return') returnDecision.mutate({
      decision: dialog.decision,
      operator: values.operator,
      justification: dialog.decision === 'LATER' ? 'Decisão adiada para verificação operacional' : values.justification,
    })
    if (dialog.kind === 'lifecycle') lifecycle.mutate({action:dialog.action,reason:values.reason})
  }
  const downloadReport = async () => {
    if (reportPending) return
    setReportPending(true); setReportError('')
    try { await api.downloadTripReport(trip.trip_key) }
    catch (error) { setReportError(error instanceof Error ? error.message : 'Não foi possível gerar o relatório.') }
    finally { setReportPending(false) }
  }

  return <div className="operational-card">
    <div className="operational-card__head"><div><span className="eyebrow">Controle operacional local</span><h3>{labels[trip.state]}</h3></div><em className={`operation-state operation-state--${trip.state.toLowerCase()}`}>{labels[trip.state]}</em></div>
    {trip.driver_divergence && <div className="driver-warning"><AlertTriangle size={16} /><strong>Divergência de condutor</strong><span>Foi mantido o último vínculo confiável.</span></div>}
    {trip.previous_driver && trip.current_driver && <div className="driver-change"><History size={15} /><span>Condutor atualizado de <strong>{trip.previous_driver}</strong> para <strong>{trip.current_driver}</strong>.</span></div>}
    {trip.state === 'CANCELADA' && <div className="driver-warning"><XCircle size={16}/><strong>Viagem cancelada</strong><span>{dateLabel(trip.cancelled_at)} · por {trip.cancelled_by_user_id || 'administrador legado'} · {trip.cancelled_reason}</span></div>}
    {trip.archived_at && <div className="driver-change"><Archive size={15}/><span>Arquivada em <strong>{dateLabel(trip.archived_at)}</strong> por {trip.archived_by_user_id || 'administrador legado'}{trip.archive_reason ? ` · ${trip.archive_reason}` : ''}.</span></div>}
    {trip.return_candidate && canEdit && <ReturnCard trip={trip} pending={returnDecision.isPending} onDecision={(decision)=>open({kind:'return',decision})} />}
    <div className="operation-grid">
      <OperationValue icon={MapPinned} label="Cerca de origem" value={fenceLabel(trip.geofences?.origin, trip.geofences?.origin_distance_m)} />
      <OperationValue icon={MapPinned} label="Cerca de destino" value={fenceLabel(trip.geofences?.destination, trip.geofences?.destination_distance_m)} />
      <OperationValue icon={Clock3} label="Chegada à origem" value={dateLabel(trip.arrived_origin_at)} />
      <OperationValue icon={Clock3} label="Início real" value={dateLabel(trip.started_at)} />
      <OperationValue icon={Clock3} label="Chegada ao destino" value={dateLabel(trip.arrived_destination_at)} />
      <OperationValue icon={CheckCircle2} label="Finalização" value={trip.finished_at ? `${dateLabel(trip.finished_at)} · ${trip.finish_type === 'automatic' ? 'automática' : 'manual'}` : 'Pendente'} />
    </div>
    <div className="operation-actions">
      {canReport&&<button onClick={downloadReport} disabled={reportPending}><Download size={14} />{reportPending ? 'Gerando PDF...' : 'Baixar relatório PDF'}</button>}
      {canCorrectStatus&&!trip.archived_at&&trip.state!=='CANCELADA'&&<button onClick={()=>open({kind:'correct'})} disabled={action.isPending}><Pencil size={14} />Corrigir horários</button>}
      {canFinalize&&!trip.archived_at&&!['FINALIZADA_NO_SISTEMA','RETORNO_CONCLUIDO','CANCELADA'].includes(trip.state)&&<button onClick={() => open({kind:'action',action:'finalize'})} disabled={action.isPending}><CheckCircle2 size={14} />Finalizar</button>}
      {canReopen&&!trip.archived_at&&trip.state === 'FINALIZADA_NO_SISTEMA' && <button onClick={() => open({kind:'action',action:'reopen'})} disabled={action.isPending}><RotateCcw size={14} />Reabrir</button>}
      {canCorrectStatus&&(trip.state === 'NO_DESTINO' || trip.state === 'NA_ORIGEM') && <button onClick={() => open({kind:'action',action:'undo_detection'})} disabled={action.isPending}><RotateCcw size={14} />Desfazer detecção</button>}
      {canCancel&&!trip.archived_at&&!['FINALIZADA_NO_SISTEMA','RETORNO_CONCLUIDO','CANCELADA'].includes(trip.state)&&<button onClick={()=>open({kind:'lifecycle',action:'cancel'})} disabled={lifecycle.isPending}><XCircle size={14}/>Cancelar viagem</button>}
      {canArchive&&!trip.archived_at&&['FINALIZADA_NO_SISTEMA','RETORNO_CONCLUIDO','CANCELADA'].includes(trip.state)&&<button onClick={()=>open({kind:'lifecycle',action:'archive'})} disabled={lifecycle.isPending}><Archive size={14}/>Arquivar</button>}
      {canArchive&&trip.archived_at&&<button onClick={()=>open({kind:'lifecycle',action:'unarchive'})} disabled={lifecycle.isPending}><ArchiveRestore size={14}/>Desarquivar</button>}
    </div>
    {canPublicLink&&<DriverPublicLink trip={trip} />}
    <OperationalObservations tripKey={trip.trip_key} stops={trip.stops ?? []}/>
    {(action.error || returnDecision.error || lifecycle.error || reportError) && <div className="form-error">{reportError || (action.error || returnDecision.error || lifecycle.error)?.message}</div>}
    {feedback && <div className="operation-feedback" role="status">{feedback}</div>}
    {canAudit&&<div className="operation-history"><h3><History size={15}/>Histórico / Auditoria operacional</h3>{audit.data?.events.length?audit.data.events.map(event=><AuditLine key={event.id} event={event}/>):<p>Nenhuma ação humana auditada nesta viagem.</p>}</div>}
    <div className="operation-history"><h3><History size={15} />Histórico</h3>{trip.events?.length ? trip.events.map((event) => <div key={event.id}><i /><span>{dateLabel(event.occurred_at)}</span><strong>{event.description}</strong><small>{event.source}{event.justification ? ` · ${event.justification}` : ''}</small></div>) : <p>Nenhum evento operacional registrado.</p>}</div>
    {dialog && <OperationalActionDialog {...dialogConfig(dialog)} context={<><strong>{trip.current_driver || 'Motorista não informado'}</strong><span>Viagem {trip.trip_key}</span><span>{trip.route?.origin_name || 'Origem não informada'} → {trip.route?.destination_name || 'Destino não informado'}</span></>} pending={action.isPending || returnDecision.isPending || lifecycle.isPending} error={(action.error || returnDecision.error || lifecycle.error)?.message} onCancel={()=>setDialog(null)} onConfirm={confirm}/>}
  </div>
}

function AuditLine({event}:{event:AuditEvent}){return <div><i/><span>{dateLabel(event.occurred_at)}</span><strong>{event.actor_display_name_snapshot} ({event.actor_role_snapshot})</strong><small>{auditLabel(event.action_type)}{event.justification?` · ${event.justification}`:''}</small></div>}
function auditLabel(value:string){return value.toLowerCase().replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase())}

function dialogConfig(dialog: DialogState): { title: string; description: string; confirmLabel: string; danger?: boolean; fields: OperationalDialogField[] } {
  if(dialog.kind==='lifecycle'){
    const content={cancel:['Cancelar viagem','O cancelamento interrompe o acompanhamento automático e revoga os links públicos ativos.','Cancelar viagem'],archive:['Arquivar viagem','A viagem sairá das listas operacionais ativas, preservando todo o histórico.','Arquivar viagem'],unarchive:['Desarquivar viagem','A viagem voltará a aparecer nas consultas operacionais.','Desarquivar viagem']} as const
    const [title,description,confirmLabel]=content[dialog.action]
    return {title,description,confirmLabel,danger:dialog.action!=='unarchive',fields:[{name:'reason',label:'Motivo / justificativa',type:'textarea',minLength:5,hint:'Informe pelo menos 5 caracteres.'}]}
  }
  if (dialog.kind === 'correct') return {
    title: 'Corrigir horário operacional', description: 'Revise o campo, o novo horário e a justificativa antes de registrar a correção.', confirmLabel: 'Registrar correção',
    fields: [
      { name:'field', label:'Campo', type:'select', options:[{value:'arrived_origin_at',label:'Chegada à origem'},{value:'started_at',label:'Início real'},{value:'arrived_destination_at',label:'Chegada ao destino'},{value:'finished_at',label:'Finalização'}] },
      { name:'value', label:'Novo horário', type:'datetime-local' },
      { name:'justification', label:'Justificativa', type:'textarea', minLength:5, hint:'Informe pelo menos 5 caracteres.' },
    ],
  }
  if (dialog.kind === 'return') return {
    title: dialog.decision === 'YES' ? 'Confirmar retorno Seven' : dialog.decision === 'NO' ? 'Confirmar retorno externo' : 'Adiar decisão de retorno',
    description: 'A decisão ficará registrada com o usuário responsável e o contexto desta viagem.', confirmLabel:'Registrar decisão', danger:dialog.decision === 'NO',
    fields: [
      {name:'operator',label:'Usuário responsável',initialValue:'operador'},
      ...(dialog.decision === 'LATER' ? [] : [{name:'justification',label:'Justificativa',type:'textarea' as const,minLength:5,hint:'Informe pelo menos 5 caracteres.'}]),
    ],
  }
  const labels = { finalize:['Finalizar viagem','Confirme o encerramento manual desta viagem.','Finalizar viagem'], reopen:['Reabrir viagem','Confirme a reabertura desta viagem finalizada.','Reabrir viagem'], undo_detection:['Desfazer detecção','Confirme a remoção da detecção automática atual.','Desfazer detecção'] } as const
  const [title,description,confirmLabel]=labels[dialog.action]
  return {title,description,confirmLabel,danger:dialog.action==='finalize',fields:[{name:'justification',label:'Justificativa',type:'textarea',minLength:5,hint:'Informe pelo menos 5 caracteres.'}]}
}

function ReturnCard({ trip, pending, onDecision }: { trip: OperationalTrip; pending: boolean; onDecision: (value: 'YES'|'NO'|'LATER')=>void }) {
  const candidate = trip.return_candidate!
  const title = candidate.state === 'RETORNO_SEVEN_CONFIRMADO' ? 'Retorno Seven confirmado' : candidate.state === 'RETORNO_EXTERNO' ? 'Retorno externo/particular' : candidate.state === 'RETORNO_CONCLUIDO' ? 'Retorno concluído' : 'Possível retorno'
  return <section className={`return-card return-card--${candidate.state.toLowerCase()}`}>
    <div className="return-card__title"><Route size={18}/><div><strong>{title}</strong><small>{candidate.state === 'AGUARDANDO_CONFIRMACAO' ? 'Aguardando confirmação' : 'Decisão operacional registrada'}</small></div></div>
    <p>O veículo permaneceu <b>{candidate.destination_stay_hours} h</b> no destino e avançou <b>{candidate.progress_toward_origin_km} km</b> em direção a Betim, dentro da rota padrão.</p>
    <div className="return-facts"><span>Compatibilidade: <b>{candidate.compatible_with_route ? 'Dentro do corredor' : 'Incompatível'}</b></span><span>Motivos: permanência mínima, saída confirmada e posições consecutivas em direção a Betim.</span></div>
    {candidate.state === 'AGUARDANDO_CONFIRMACAO' && <><h4>Esta viagem de retorno pertence à Seven Cargo?</h4><div className="return-actions"><button onClick={()=>onDecision('YES')} disabled={pending}>Sim</button><button onClick={()=>onDecision('NO')} disabled={pending}>Não</button><button onClick={()=>onDecision('LATER')} disabled={pending}>Verificar depois</button></div></>}
    {candidate.decision_at && <small>Decisão em {dateLabel(candidate.decision_at)} por {candidate.decided_by || 'operador'}.</small>}
  </section>
}

function OperationValue({ icon: Icon, label, value }: { icon: typeof Clock3; label: string; value: string }) { return <div><Icon size={15} /><span>{label}</span><strong>{value}</strong></div> }
function dateLabel(value?: string | null) { return value ? new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' }) : 'Não registrado' }
function fenceLabel(value?: string, distance?: number) { return `${value === 'inside' ? 'Dentro' : value === 'outside' ? 'Fora' : 'Sem dados'}${distance != null ? ` · ${Math.round(distance)} m` : ''}` }
