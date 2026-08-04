const CENTRAL_WHATSAPP_NUMBER = '553584027743'
const CENTRAL_WHATSAPP_MESSAGE = 'Olá, Central Seven Cargo. Estou acessando o Portal do Motorista e preciso de auxílio.'

export function buildCentralWhatsAppUrl(): string {
  return `https://wa.me/${CENTRAL_WHATSAPP_NUMBER}?text=${encodeURIComponent(CENTRAL_WHATSAPP_MESSAGE)}`
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
