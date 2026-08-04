import type { PublicLinkCreated, PublicLinkStatus } from '../types'

export type PublicLinkState = 'active' | 'expired' | 'revoked' | 'inactive'
export type DisplayedPublicLink = PublicLinkStatus & { url: string | null }

export function createdPublicLink(created: PublicLinkCreated, url: string): DisplayedPublicLink {
  return { ...created, id: String(created.id), url, access_count: 0 }
}

export function mergePublicLinkStatus(
  previous: DisplayedPublicLink | null,
  status: PublicLinkStatus,
): DisplayedPublicLink {
  const normalized = { ...status, id: String(status.id) }
  if (previous && String(previous.id) === String(status.id)) {
    return { ...previous, ...normalized, url: previous.url }
  }
  return { ...normalized, url: null }
}

export function linkIsUnavailable(link: Pick<DisplayedPublicLink, 'active' | 'expires_at' | 'revoked_at'>): boolean {
  return !link.active
    || Boolean(link.revoked_at)
    || Boolean(link.expires_at && new Date(link.expires_at).getTime() <= Date.now())
}

export function managedPublicUrl(returnedUrl: string, configuredBase?: string): string {
  const parsed = new URL(returnedUrl)
  const token = parsed.pathname.split('/').filter(Boolean).at(-1)
  if (!token || !/^[A-Za-z0-9_-]{43,128}$/.test(token)) {
    throw new Error('O servidor retornou um link público inválido.')
  }
  const base = (configuredBase || window.location.origin).replace(/\/$/, '').replace(/\/viagem$/, '')
  return `${base}/viagem/${token}`
}

export function publicLinkState(status: PublicLinkStatus): PublicLinkState {
  if (status.active) return 'active'
  if (status.revoked_at) return 'revoked'
  if (status.expires_at && new Date(status.expires_at).getTime() <= Date.now()) return 'expired'
  return 'inactive'
}

export function whatsappShareUrl(driverName: string, link: string): string {
  const message = `Olá, ${driverName}.

Segue o link para acompanhamento da sua viagem Seven Cargo:

${link}

Por esse link você poderá consultar a rota, o status atual e a previsão de chegada.

Em caso de dúvida ou ocorrência, entre em contato com a Central Seven Cargo.`
  return `https://wa.me/?text=${encodeURIComponent(message)}`
}
