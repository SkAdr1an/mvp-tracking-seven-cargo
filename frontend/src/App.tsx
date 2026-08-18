import { useEffect, useState } from 'react'
import { ADMIN_SESSION_EXPIRED_EVENT, PANEL_FORBIDDEN_EVENT, api } from './api'
import { Header } from './components/Header'
import { ContentErrorBoundary } from './components/ContentErrorBoundary'
import { Sidebar } from './components/Sidebar'
import { useFleetTracking } from './hooks/useFleetTracking'
import { Drivers } from './pages/Drivers'
import { Integrations } from './pages/Integrations'
import { Overview } from './pages/Overview'
import { Routes } from './pages/Routes'
import { Trafegus } from './pages/Trafegus'
import { AngelLiraAdmin } from './pages/AngelLiraAdmin'
import { UsersAdmin } from './pages/UsersAdmin'
import { Audit } from './pages/Audit'
import { LoginPage } from './components/login/LoginPage'
import { SessionContext, hasPermission } from './permissions'
import type { Driver, Page, PanelSession } from './types'
import { DriverHistory } from './pages/DriverHistory'
import { PendingEvaluations } from './pages/PendingEvaluations'
import './mobile-shell.css'
import './premium-dashboard.css'
import './premium-kpi-labels.css'

export default function App() {
  const [session, setSession] = useState<PanelSession | null>()
  useEffect(() => { api.panelMe().then(setSession).catch(() => setSession(null)) }, [])
  useEffect(() => {
    const expired = () => setSession(null)
    window.addEventListener(ADMIN_SESSION_EXPIRED_EVENT, expired)
    return () => window.removeEventListener(ADMIN_SESSION_EXPIRED_EVENT, expired)
  }, [])
  if (session === undefined) return <div className="auth-shell"><div className="auth-card"><p>Verificando sessão segura...</p></div></div>
  if (session === null) return <PanelLogin onAuthenticated={setSession} />
  return <AuthenticatedApp session={session} onLogout={async () => { await api.panelLogout(); setSession(null) }} />
}

function AuthenticatedApp({ session, onLogout }: { session: PanelSession; onLogout: () => Promise<void> }) {
  const [page, setPage] = useState<Page>('overview')
  const [menuOpen, setMenuOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string>()
  const [adminApiConnection,setAdminApiConnection]=useState<'connecting'|'connected'|'disconnected'>('connecting')
  const [hiddenDriverIds,setHiddenDriverIds]=useState<string[]>(()=>stored('seven-hidden-drivers',[]))
  const [pinnedDriverId,setPinnedDriverId]=useState<string|undefined>(()=>stored('seven-pinned-driver',undefined))
  const [forbidden,setForbidden]=useState('')
  useEffect(()=>{const show=()=>setForbidden('Você não possui permissão para realizar esta ação.');window.addEventListener(PANEL_FORBIDDEN_EVENT,show);return()=>window.removeEventListener(PANEL_FORBIDDEN_EVENT,show)},[])
  useEffect(()=>localStorage.setItem('seven-hidden-drivers',JSON.stringify(hiddenDriverIds)),[hiddenDriverIds])
  useEffect(()=>pinnedDriverId?localStorage.setItem('seven-pinned-driver',JSON.stringify(pinnedDriverId)):localStorage.removeItem('seven-pinned-driver'),[pinnedDriverId])
  const { drivers, connection, reconnect, fleet, source, traffic, paths, sites, refreshTraffic } = useFleetTracking()
  const selected = drivers.find((driver) => driver.id === selectedId)
  const selectDriver = (driver: Driver) => { setSelectedId(driver.id) }
  useEffect(() => {
    if (!menuOpen) return
    const previousOverflow = document.body.style.overflow
    const menuButton = document.querySelector<HTMLElement>('.menu-button')
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', closeOnEscape)
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>('#primary-navigation .sidebar__close')?.focus())
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', closeOnEscape)
      menuButton?.focus()
    }
  }, [menuOpen])

  return <SessionContext.Provider value={session}><div className="app-shell">
    <Sidebar page={page} onChange={setPage} open={menuOpen} onClose={() => setMenuOpen(false)} />
    {menuOpen && <button className="sidebar-backdrop" onClick={() => setMenuOpen(false)} aria-label="Fechar menu" />}
    <main className="main-content">
      <Header page={page} connection={page==='driver-history'||page==='pending-evaluations'?adminApiConnection:connection} apiMode={page==='driver-history'||page==='pending-evaluations'} menuOpen={menuOpen} attentionCount={fleet?.counts.attention ?? 0} criticalCount={fleet?.counts.critical ?? 0} username={session.username} role={session.role} onLogout={onLogout} onMenu={() => setMenuOpen(true)} onReconnect={reconnect} />
      <div className="page-content">
        {forbidden&&<div className="form-error" role="alert" onClick={()=>setForbidden('')}>{forbidden}</div>}
        <ContentErrorBoundary resetKey={`${page}:${selectedId ?? ''}`} onOverview={() => { setSelectedId(undefined); setPage('overview') }}>
        {page === 'overview' && <Overview drivers={drivers} selected={selected} hiddenDriverIds={hiddenDriverIds} pinnedDriverId={pinnedDriverId} onSelect={(driver) => { setSelectedId(driver.id) }} onClear={()=>setSelectedId(undefined)} onOpenDrivers={() => setPage('drivers')} fleet={fleet} source={source} traffic={traffic} paths={paths} sites={sites} onTrafficChanged={refreshTraffic} />}
        {page === 'drivers' && <Drivers drivers={drivers} selected={selected} hiddenDriverIds={hiddenDriverIds} pinnedDriverId={pinnedDriverId} onSelect={selectDriver} onClear={()=>setSelectedId(undefined)} onHide={(id)=>{setHiddenDriverIds((value)=>[...new Set([...value,id])]);if(pinnedDriverId===id)setPinnedDriverId(undefined)}} onRestore={(id)=>setHiddenDriverIds((value)=>value.filter((item)=>item!==id))} onRestoreAll={()=>setHiddenDriverIds([])} onPin={(id)=>{setPinnedDriverId((value)=>value===id?undefined:id);setSelectedId(id)}} />}
        {page === 'driver-history' && <DriverHistory onConnection={setAdminApiConnection} />}
        {page === 'pending-evaluations' && <PendingEvaluations onConnection={setAdminApiConnection} />}
        {page === 'routes' && <Routes />}
        {page === 'trafegus' && <Trafegus />}
        {page === 'integrations' && <Integrations />}
        {page === 'angellira' && hasPermission(session,'settings:read') && <AngelLiraAdmin />}
        {page === 'users' && hasPermission(session,'users:read') && <UsersAdmin />}
        {page === 'audit' && hasPermission(session,'audit:read-full') && <Audit />}
        </ContentErrorBoundary>
      </div>
    </main>
  </div></SessionContext.Provider>
}

function PanelLogin({ onAuthenticated }: { onAuthenticated: (session: PanelSession) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setPending(true); setError('')
    try { onAuthenticated(await api.panelLogin({ username, password })) }
    catch { setError('Não foi possível entrar. Verifique as credenciais ou tente novamente mais tarde.') }
    finally { setPending(false); setPassword('') }
  }
  return <LoginPage username={username} password={password} error={error} pending={pending} onUsernameChange={setUsername} onPasswordChange={setPassword} onSubmit={submit}/>
}

function stored<T>(key:string,fallback:T):T{try{const value=localStorage.getItem(key);return value?JSON.parse(value) as T:fallback}catch{return fallback}}
