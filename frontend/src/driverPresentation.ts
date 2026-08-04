import type { Driver } from './types'

export type OperationalAvailability = {
  code: 'ROUTE_NOT_RECOGNIZED'|'ROUTE_CONFIG_UNAVAILABLE'|'ROUTE_GEOMETRY_UNAVAILABLE'|'POSITION_UNAVAILABLE'|'OPERATIONAL_DATA_INCOMPLETE'|'DRIVER_LINK_INCONSISTENT'
  message: string
}

export function operationalAvailability(driver: Driver): OperationalAvailability | undefined {
  const recognition=driver.route_recognition
  if(recognition?.status==='UNIDENTIFIED'||recognition?.status==='AMBIGUOUS')return {code:'ROUTE_NOT_RECOGNIZED',message:'Rota ainda não reconhecida'}
  if(recognition?.status==='GEOMETRY_PENDING'||driver.route_progress?.reason==='geometry_unavailable')return {code:'ROUTE_GEOMETRY_UNAVAILABLE',message:'Geometria da rota indisponível'}
  if(recognition?.status==='RECOGNIZED'&&!driver.operational?.route)return {code:'ROUTE_CONFIG_UNAVAILABLE',message:'Configuração da rota indisponível'}
  if(!driver.location)return {code:'POSITION_UNAVAILABLE',message:'Posição atual indisponível'}
  if(driver.operational?.driver_divergence)return {code:'DRIVER_LINK_INCONSISTENT',message:'Vínculo operacional inconsistente'}
  const progress=driver.route_progress
  if(progress&&![progress.total_distance_km,progress.advanced_distance_km,progress.remaining_distance_km,progress.progress_percent].every((value)=>typeof value==='number'&&Number.isFinite(value)))return {code:'OPERATIONAL_DATA_INCOMPLETE',message:'Informação operacional incompleta'}
  return undefined
}

export function progressLabel(driver: Pick<Driver, 'route_progress'>): string {
  const progress = driver.route_progress?.progress_percent
  return typeof progress === 'number' && Number.isFinite(progress)
    ? `${progress.toLocaleString('pt-BR')}%`
    : 'Indisponível'
}
