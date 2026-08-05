import { useEffect, useState } from 'react'
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
import type { Driver, Page } from './types'
import './mobile-shell.css'

export default function App() {
  const [page, setPage] = useState<Page>('overview')
  const [menuOpen, setMenuOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string>()
  const [hiddenDriverIds,setHiddenDriverIds]=useState<string[]>(()=>stored('seven-hidden-drivers',[]))
  const [pinnedDriverId,setPinnedDriverId]=useState<string|undefined>(()=>stored('seven-pinned-driver',undefined))
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

  return <div className="app-shell">
    <Sidebar page={page} onChange={setPage} open={menuOpen} onClose={() => setMenuOpen(false)} />
    {menuOpen && <button className="sidebar-backdrop" onClick={() => setMenuOpen(false)} aria-label="Fechar menu" />}
    <main className="main-content">
      <Header page={page} connection={connection} menuOpen={menuOpen} attentionCount={fleet?.counts.attention ?? 0} criticalCount={fleet?.counts.critical ?? 0} onMenu={() => setMenuOpen(true)} onReconnect={reconnect} />
      <div className="page-content">
        <ContentErrorBoundary resetKey={`${page}:${selectedId ?? ''}`} onOverview={() => { setSelectedId(undefined); setPage('overview') }}>
        {page === 'overview' && <Overview drivers={drivers} selected={selected} hiddenDriverIds={hiddenDriverIds} pinnedDriverId={pinnedDriverId} onSelect={(driver) => { setSelectedId(driver.id) }} onClear={()=>setSelectedId(undefined)} onOpenDrivers={() => setPage('drivers')} fleet={fleet} source={source} traffic={traffic} paths={paths} sites={sites} onTrafficChanged={refreshTraffic} />}
        {page === 'drivers' && <Drivers drivers={drivers} selected={selected} hiddenDriverIds={hiddenDriverIds} pinnedDriverId={pinnedDriverId} onSelect={selectDriver} onClear={()=>setSelectedId(undefined)} onHide={(id)=>{setHiddenDriverIds((value)=>[...new Set([...value,id])]);if(pinnedDriverId===id)setPinnedDriverId(undefined)}} onRestore={(id)=>setHiddenDriverIds((value)=>value.filter((item)=>item!==id))} onRestoreAll={()=>setHiddenDriverIds([])} onPin={(id)=>{setPinnedDriverId((value)=>value===id?undefined:id);setSelectedId(id)}} />}
        {page === 'routes' && <Routes />}
        {page === 'trafegus' && <Trafegus />}
        {page === 'integrations' && <Integrations />}
        {page === 'angellira' && <AngelLiraAdmin />}
        </ContentErrorBoundary>
      </div>
    </main>
  </div>
}

function stored<T>(key:string,fallback:T):T{try{const value=localStorage.getItem(key);return value?JSON.parse(value) as T:fallback}catch{return fallback}}
