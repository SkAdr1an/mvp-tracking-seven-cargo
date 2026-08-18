import { CloudSun, Database, History, Map, Route, Settings2, Truck, Users, Waypoints, X } from 'lucide-react'
import type { Page } from '../types'
import { usePanelSession, hasPermission } from '../permissions'

const items: { page: Page; label: string; icon: typeof Map; permission?:string }[] = [
  { page: 'overview', label: 'Visão geral', icon: Map },
  { page: 'drivers', label: 'Motoristas', icon: Truck },
  { page: 'routes', label: 'Planejar rota', icon: Route, permission:'integrations:invoke' },
  { page: 'trafegus', label: 'Trafegus', icon: Waypoints, permission:'integrations:invoke' },
  { page: 'integrations', label: 'Integrações', icon: CloudSun },
  { page: 'angellira', label: 'Base AngelLira', icon: Database, permission:'settings:read' },
  { page: 'users', label: 'Usuários', icon: Users, permission:'users:read' },
  { page: 'audit', label: 'Auditoria', icon: History, permission:'audit:read-full' },
]

export function Sidebar({ page, onChange, open, onClose }: {
  page: Page
  onChange: (page: Page) => void
  open: boolean
  onClose: () => void
}) {
  const session=usePanelSession()
  return (
    <aside id="primary-navigation" className={`sidebar ${open ? 'sidebar--open' : ''}`}>
      <div className="brand">
        <img className="brand__logo" src="/login/seven-cargo-logo.png" alt="Seven Cargo" />
        <div><strong>Seven Cargo</strong><small>Central de operações</small></div>
        <button type="button" className="icon-button sidebar__close" onClick={onClose} aria-label="Fechar menu"><X size={20} /></button>
      </div>
      <nav className="nav" aria-label="Navegação principal">
        <span className="nav__eyebrow">Operação</span>
        {items.filter((item)=>!item.permission||hasPermission(session,item.permission)).map(({ page: itemPage, label, icon: Icon }) => (
          <button
            type="button"
            key={itemPage}
            className={`nav__item ${page === itemPage ? 'nav__item--active' : ''}`}
            onClick={() => { onChange(itemPage); onClose() }}
            aria-current={page === itemPage ? 'page' : undefined}
          >
            <Icon size={19} strokeWidth={1.8} /> <span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar__footer">
        <Settings2 size={17} />
        <div><span>Ambiente MVP</span><small>Operação conectada</small></div>
      </div>
    </aside>
  )
}
