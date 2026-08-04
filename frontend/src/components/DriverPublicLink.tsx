import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useEffect, useRef, useState } from 'react'
import { Copy, ExternalLink, Link2, LogIn, LogOut, MessageCircle, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { ADMIN_SESSION_EXPIRED_EVENT, api } from '../api'
import type { OperationalTrip, PanelSession, PublicLinkStatus } from '../types'
import { createdPublicLink, type DisplayedPublicLink, linkIsUnavailable, managedPublicUrl, mergePublicLinkStatus, publicLinkState, whatsappShareUrl } from './publicLinkUtils'
import './driver-public-link.css'

const PUBLIC_APP_URL = import.meta.env.VITE_PUBLIC_APP_URL || window.location.origin

export function DriverPublicLink({ trip }: { trip: OperationalTrip }) {
  const queryClient = useQueryClient()
  const [link, setLink] = useState<DisplayedPublicLink | null>(null)
  const [feedback, setFeedback] = useState('')
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)
  const linkRef = useRef<DisplayedPublicLink | null>(null)
  const tripKeyRef = useRef(trip.trip_key)
  const creationInFlightRef = useRef(false)
  const creationSequenceRef = useRef(0)
  tripKeyRef.current = trip.trip_key
  const storeLink = (value: DisplayedPublicLink | null) => {
    linkRef.current = value
    setLink(value)
  }
  const session = useQuery({
    queryKey: ['panel-session'],
    queryFn: api.panelSession,
    retry: false,
    staleTime: 5 * 60_000,
  })
  const status = useQuery({
    queryKey: ['public-link', trip.trip_key],
    queryFn: () => api.publicLinkStatus(trip.trip_key),
    enabled: Boolean(session.data),
    retry: false,
  })
  useEffect(() => {
    const expireSession = () => {
      creationInFlightRef.current = false
      queryClient.setQueryData(['panel-session'], null)
      queryClient.removeQueries({ queryKey: ['public-link'] })
      storeLink(null)
      setSessionExpired(true)
      setFeedback('')
    }
    window.addEventListener(ADMIN_SESSION_EXPIRED_EVENT, expireSession)
    return () => window.removeEventListener(ADMIN_SESSION_EXPIRED_EVENT, expireSession)
  }, [queryClient])
  useEffect(() => {
    storeLink(null)
    setFeedback('')
  }, [trip.trip_key])
  useEffect(() => {
    const current = status.data
    const previous = linkRef.current
    if (!current) return
    const merged = mergePublicLinkStatus(previous, current)
    const finished = trip.state === 'FINALIZADA_NO_SISTEMA' || trip.state === 'RETORNO_CONCLUIDO'
    const replaced = Boolean(previous?.url && String(previous.id) !== String(current.id))
    const unavailable = linkIsUnavailable(merged) || finished
    storeLink(unavailable ? { ...merged, url: null, active: false } : merged)
    if (previous?.url && (replaced || unavailable)) {
      setFeedback('O link exibido foi substituído ou deixou de estar ativo.')
    }
  }, [status.data, trip.state])
  const login = useMutation({
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['public-link'] })
      setFeedback('')
    },
    mutationFn: async (credentials: { username: string; password: string }) => {
      await api.panelLogin(credentials)
      return api.panelMe()
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['panel-session'], data)
      setSessionExpired(false)
      create.reset()
      revoke.reset()
      setFeedback('Autenticação realizada com sucesso.')
      void queryClient.invalidateQueries({ queryKey: ['public-link', trip.trip_key] })
    },
  })
  const logout = useMutation({
    mutationFn: api.panelLogout,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['panel-session'] })
      queryClient.removeQueries({ queryKey: ['public-link', trip.trip_key] })
      storeLink(null)
      setSessionExpired(false)
      setFeedback('')
      void session.refetch()
    },
  })
  const create = useMutation({
    mutationFn: () => api.createPublicLink(trip.trip_key),
    onMutate: async () => {
      const sequence = ++creationSequenceRef.current
      const tripKey = trip.trip_key
      await queryClient.cancelQueries({ queryKey: ['public-link', tripKey] })
      setFeedback('')
      return { sequence, tripKey }
    },
    onSuccess: (created, _variables, context) => {
      if (!context || context.sequence !== creationSequenceRef.current || context.tripKey !== tripKeyRef.current) return
      const url = managedPublicUrl(created.url, PUBLIC_APP_URL)
      const authoritative = createdPublicLink(created, url)
      storeLink(authoritative)
      queryClient.setQueryData<PublicLinkStatus>(['public-link', context.tripKey], authoritative)
      setFeedback('Link criado. Copie ou compartilhe esta URL agora.')
      void status.refetch()
    },
    onSettled: () => {
      creationInFlightRef.current = false
    },
  })
  const revoke = useMutation({
    mutationFn: () => api.revokePublicLink(trip.trip_key),
    onSuccess: () => {
      storeLink(null)
      setConfirmRevoke(false)
      setFeedback('Link revogado. O motorista não poderá mais utilizá-lo.')
      void status.refetch()
    },
  })

  return <section className="driver-public-link" aria-labelledby="driver-public-link-title">
    <header>
      <div><span className="eyebrow">Acesso público seguro</span><h3 id="driver-public-link-title"><Link2 size={17}/>Link do motorista</h3></div>
      {session.data && <button className="link-logout" onClick={() => logout.mutate()} disabled={logout.isPending}><LogOut size={14}/>Sair</button>}
    </header>
    {session.isLoading
      ? <div className="link-loading"><RefreshCw className="spin" size={17}/>Verificando autenticação...</div>
      : !session.data
        ? <PanelLogin expired={sessionExpired} pending={login.isPending} error={login.error?.message} onSubmit={(credentials) => login.mutate(credentials)} />
        : <LinkAdministration
            trip={trip}
            session={session.data}
            status={status.data}
            statusLoading={status.isLoading}
            url={link?.url || ''}
            feedback={feedback}
            error={(status.error || create.error || revoke.error)?.message}
            creating={create.isPending}
            revoking={revoke.isPending}
            confirmRevoke={confirmRevoke}
            onCreate={() => {
              if (creationInFlightRef.current || create.isPending) return
              creationInFlightRef.current = true
              setFeedback('')
              create.mutate()
            }}
            onRevoke={() => revoke.mutate()}
            onConfirmRevoke={setConfirmRevoke}
            onFeedback={setFeedback}
          />}
  </section>
}

function PanelLogin({ expired, pending, error, onSubmit }: {
  expired: boolean
  pending: boolean
  error?: string
  onSubmit: (input: { username: string; password: string }) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit({ username: username.trim(), password })
  }
  return <form className="link-login" onSubmit={submit}>
    <div><ShieldCheck size={18}/><p><strong>{expired ? 'Sua sessão expirou.' : 'Autenticação necessária'}</strong><span>{expired ? 'Entre novamente para continuar nesta viagem.' : 'Entre com o usuário autorizado do painel para administrar este link.'}</span></p></div>
    <label><span>Usuário</span><input required autoComplete="username" value={username} onChange={(event)=>setUsername(event.target.value)}/></label>
    <label><span>Senha</span><input required type="password" autoComplete="current-password" value={password} onChange={(event)=>setPassword(event.target.value)}/></label>
    {error && <small role="alert">{translateAuthError(error)}</small>}
    <button type="submit" disabled={pending}><LogIn size={15}/>{pending ? 'Entrando...' : expired ? 'Entrar novamente' : 'Entrar'}</button>
  </form>
}

function LinkAdministration({ trip, session, status, statusLoading, url, feedback, error, creating, revoking, confirmRevoke, onCreate, onRevoke, onConfirmRevoke, onFeedback }: {
  trip: OperationalTrip
  session: PanelSession
  status?: PublicLinkStatus | null
  statusLoading: boolean
  url: string
  feedback: string
  error?: string
  creating: boolean
  revoking: boolean
  confirmRevoke: boolean
  onCreate: () => void
  onRevoke: () => void
  onConfirmRevoke: (value: boolean) => void
  onFeedback: (value: string) => void
}) {
  const state = status ? publicLinkState(status) : null
  const canRevoke = state === 'active'
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      onFeedback('Link copiado para a área de transferência.')
    } catch {
      onFeedback('Não foi possível copiar automaticamente. Selecione o link exibido e copie manualmente.')
    }
  }
  return <div className="link-admin">
    <div className="link-session"><ShieldCheck size={15}/><span>Autenticado como <strong>{session.username}</strong></span></div>
    {statusLoading
      ? <div className="link-loading"><RefreshCw className="spin" size={17}/>Consultando o link...</div>
      : status
        ? <div className="link-status">
            <div><span>Situação</span><strong className={`link-state link-state--${state}`}>{stateLabel(state)}</strong></div>
            <div><span>Criado em</span><strong>{dateLabel(status.created_at)}</strong></div>
            <div><span>Último acesso</span><strong>{status.last_access_at ? dateLabel(status.last_access_at) : 'Ainda não acessado'}</strong></div>
          </div>
        : <p className="link-empty">Nenhum link foi gerado para esta viagem.</p>}

    {url && <div className="link-created"><label><span>Link recém-gerado</span><input readOnly value={url} onFocus={(event)=>event.currentTarget.select()}/></label><small>Por segurança, esta URL só fica disponível após a geração. Copie ou compartilhe agora.</small></div>}

    <div className="link-actions">
      {(!status || !canRevoke || !url) && <button onClick={onCreate} disabled={creating}>{creating ? <><RefreshCw className="spin" size={15}/>Gerando novo link...</> : <><Link2 size={15}/>{status ? 'Gerar novo link' : 'Gerar link'}</>}</button>}
      {url && <><button onClick={() => void copy()}><Copy size={15}/>Copiar link</button><a href={url} target="_blank" rel="noopener noreferrer"><ExternalLink size={15}/>Abrir em nova aba</a><a className="whatsapp-action" href={whatsappShareUrl(trip.current_driver || 'motorista', url)} target="_blank" rel="noopener noreferrer"><MessageCircle size={15}/>Compartilhar pelo WhatsApp</a></>}
      {canRevoke && !confirmRevoke && <button className="link-danger" onClick={()=>onConfirmRevoke(true)}><Trash2 size={15}/>Revogar</button>}
      {canRevoke && confirmRevoke && <div className="link-revoke-confirm"><span>Revogar este link agora?</span><button className="link-danger" onClick={onRevoke} disabled={revoking}>{revoking ? 'Revogando...' : 'Confirmar'}</button><button onClick={()=>onConfirmRevoke(false)}>Cancelar</button></div>}
    </div>
    {feedback && <div className="operation-feedback" role="status">{feedback}</div>}
    {error && <div className="form-error" role="alert">{error}</div>}
  </div>
}

function stateLabel(state: ReturnType<typeof publicLinkState> | null) {
  return state === 'active' ? 'Ativo' : state === 'expired' ? 'Expirado' : state === 'revoked' ? 'Revogado' : 'Inativo'
}
function dateLabel(value: string) { return new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' }) }
function translateAuthError(value: string) {
  return value === 'Invalid username or password' ? 'Usuário ou senha inválidos.' : value === 'Panel authentication is not configured' ? 'A autenticação do painel ainda não foi configurada no servidor.' : value
}
