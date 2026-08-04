export function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function validCoordinates(latitude: unknown, longitude: unknown): boolean {
  const lat = finiteNumber(latitude)
  const lon = finiteNumber(longitude)
  return lat !== undefined && lon !== undefined && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
}

export function validDate(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined
  return Number.isFinite(new Date(value).getTime()) ? value : undefined
}

export function sanitizedErrorContext(error: unknown): { name: string; message: string } {
  const source = error instanceof Error ? error : new Error('Erro de renderização desconhecido')
  const message = source.message
    .replace(/https?:\/\/\S+/gi, '[url]')
    .replace(/\b(?:token|password|senha|cookie|authorization)\s*[=:]\s*\S+/gi, '$1=[redacted]')
    .slice(0, 300)
  return { name: source.name.slice(0, 80), message }
}
