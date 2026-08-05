const CENTRAL_WHATSAPP_NUMBER = '553584027743'
import type { PublicTrip } from './types'

function clean(value?: string | null): string | null {
  const text = value?.trim()
  if (!text || /^(undefined|null|motorista não informado)$/i.test(text)) return null
  return text
}

function place(placeValue: PublicTrip['route']['origin']): string | null {
  const locality = clean(placeValue.city) && clean(placeValue.state)
    ? `${clean(placeValue.city)}/${clean(placeValue.state)}` : clean(placeValue.city) || clean(placeValue.state)
  return locality || clean(placeValue.name)
}

export function buildCentralWhatsAppMessage(trip: PublicTrip): string {
  const name = clean(trip.driver_name)
  const reference = clean(trip.trip_reference)
  const origin = place(trip.route.origin)
  const destination = place(trip.route.destination)
  const plate = clean(trip.vehicle.plate)
  const parts: string[] = []
  if (name) parts.push(`Sou ${name}`)
  if (reference) parts.push(`${name ? 'viagem' : 'Viagem'} ${reference}`)
  if (origin && destination) parts.push(`na rota ${origin} → ${destination}`)
  if (plate) parts.push(`veículo ${plate}`)
  const identification = parts.join(', ')
  return `Olá, Central Seven Cargo!${identification ? ` ${identification}.` : ''} Preciso de atendimento.`
}

export function buildCentralWhatsAppUrl(trip: PublicTrip): string {
  return `https://wa.me/${CENTRAL_WHATSAPP_NUMBER}?text=${encodeURIComponent(buildCentralWhatsAppMessage(trip))}`
}

export function locationAgeLabel(recordedAt?: string | null, now = Date.now()): string {
  if (!recordedAt) return 'Horário indisponível'
  const value = new Date(recordedAt).getTime()
  if (!Number.isFinite(value)) return 'Horário indisponível'
  const minutes = Math.max(0, Math.floor((now - value) / 60_000))
  if (minutes < 1) return 'Atualizada agora'
  if (minutes === 1) return 'Atualizada há 1 minuto'
  if (minutes < 60) return `Atualizada há ${minutes} minutos`
  const hours = Math.floor(minutes / 60)
  return hours === 1 ? 'Atualizada há 1 hora' : `Atualizada há ${hours} horas`
}
