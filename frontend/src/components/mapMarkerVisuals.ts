import type { IncidentCategory, TrafficIncident, WeatherRisk } from '../types'

export type TrafficVisualKind = 'accident'|'congestion'|'slow'|'works'|'closure'|'stopped'|'hazard'|'manual'|'other'
export type WeatherVisualKind = 'light-rain'|'heavy-rain'|'storm'|'fog'|'wind'|'weather'
export type MarkerSeverity = 'info'|'attention'|'critical'

const trafficKinds: Record<IncidentCategory, TrafficVisualKind> = {
  ACIDENTE: 'accident', CONGESTIONAMENTO: 'congestion', TRANSITO_LENTO: 'slow', OBRA: 'works',
  INTERDICAO: 'closure', VIA_FECHADA: 'closure', VEICULO_PARADO: 'stopped', RISCO_VIA: 'hazard',
  RISCO_CLIMATICO: 'hazard', OCORRENCIA_MANUAL: 'manual', OUTRO: 'other',
}
const trafficLabels: Record<TrafficVisualKind,string> = {
  accident:'Acidente', congestion:'Congestionamento', slow:'Trânsito lento', works:'Obra na via',
  closure:'Via fechada ou interditada', stopped:'Veículo parado', hazard:'Risco na via',
  manual:'Ocorrência manual', other:'Outra ocorrência',
}
const weatherLabels: Record<WeatherVisualKind,string> = {
  'light-rain':'Chuva leve', 'heavy-rain':'Chuva forte', storm:'Tempestade', fog:'Baixa visibilidade',
  wind:'Vento forte', weather:'Risco climático',
}

export function trafficVisual(incident: Pick<TrafficIncident,'category'|'severity'|'manual'>) {
  const kind = incident.manual ? 'manual' : trafficKinds[incident.category] || 'other'
  const severity: MarkerSeverity = incident.severity === 'CRITICO' ? 'critical' : incident.severity === 'ATENCAO' ? 'attention' : 'info'
  return {kind,severity,label:trafficLabels[kind]}
}

export function weatherVisual(risk: Pick<WeatherRisk,'type'|'severity'|'rain_3h_mm'>) {
  const type=String(risk.type||'').toLowerCase();const rain=Number(risk.rain_3h_mm||0)
  let kind:WeatherVisualKind='weather'
  if(type==='thunderstorm')kind='storm'
  else if(type==='heavy_rain'||rain>=10)kind='heavy-rain'
  else if(type==='rain'||type.includes('drizzle'))kind='light-rain'
  else if(type==='low_visibility'||type.includes('fog')||type.includes('mist'))kind='fog'
  else if(type==='strong_wind'||type.includes('wind'))kind='wind'
  const normalized=String(risk.severity||'').toLowerCase()
  const severity:MarkerSeverity=normalized==='high'||normalized==='critical'||kind==='storm'?'critical':normalized==='low'?'info':'attention'
  return {kind,severity,label:weatherLabels[kind]}
}
