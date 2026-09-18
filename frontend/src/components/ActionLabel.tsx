interface ActionLabelProps {
  actionType: string
  className?: string
}

const actionLabels: Record<string, string> = {
  AUTH_LOGIN_SUCCESS: 'Login realizado',
  AUTH_LOGIN_FAILURE: 'Falha de login',
  AUTH_LOGOUT: 'Logout',
  USER_CREATED: 'Usuário criado',
  USER_UPDATED: 'Usuário atualizado',
  USER_DELETED: 'Usuário deletado',
  USER_ROLE_CHANGED: 'Perfil alterado',
  USER_PASSWORD_CHANGED: 'Senha alterada',
  TRIP_CREATED: 'Viagem criada',
  TRIP_STARTED: 'Viagem iniciada',
  TRIP_FINALIZED: 'Viagem finalizada',
  TRIP_CANCELLED: 'Viagem cancelada',
  TRIP_ARCHIVED: 'Viagem arquivada',
  TRIP_REOPENED: 'Viagem reaberta',
  TRIP_CORRECTED: 'Viagem corrigida',
  DRIVER_CREATED: 'Motorista criado',
  DRIVER_UPDATED: 'Motorista atualizado',
  DRIVER_IDENTIFIED: 'Motorista identificado',
  DRIVER_EVALUATION_CREATED: 'Avaliação criada',
  DRIVER_EVALUATION_UPDATED: 'Avaliação alterada',
  DRIVER_NOTE_CREATED: 'Observação criada',
  DRIVER_NOTE_UPDATED: 'Observação alterada',
  DRIVER_PUNCTUALITY_ADJUSTED: 'Pontualidade ajustada',
  INCIDENT_CREATED: 'Incidente criado',
  INCIDENT_UPDATED: 'Incidente atualizado',
  INCIDENT_RESOLVED: 'Incidente resolvido',
  REPORT_GENERATED: 'Relatório gerado',
  REPORT_DOWNLOADED: 'Relatório baixado',
  OBSERVATION_CREATED: 'Observação criada',
  OBSERVATION_UPDATED: 'Observação alterada',
  OBSERVATION_DELETED: 'Observação deletada',
  RETURN_DETECTED: 'Possível retorno detectado',
  RETURN_CONFIRMED: 'Retorno confirmado',
  RETURN_REJECTED: 'Retorno rejeitado',
  INTEGRATION_SYNC: 'Sincronização de integração',
  INTEGRATION_ERROR: 'Erro de integração',
}

export function ActionLabel({ actionType, className }: ActionLabelProps) {
  const normalized = actionType.replaceAll('_', ' ')
  const label = actionLabels[actionType] || normalized.charAt(0).toUpperCase() + normalized.slice(1).toLowerCase()

  return (
    <span className={`action-label ${className || ''}`} title={actionType}>
      {label}
    </span>
  )
}
