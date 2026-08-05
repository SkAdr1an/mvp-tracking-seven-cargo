import { CloudSun, Database, Map, Route, Settings2, Truck, Waypoints, X } from 'lucide-react'
import type { Page } from '../types'

const items: { page: Page; label: string; icon: typeof Map }[] = [
  { page: 'overview', label: 'Visão geral', icon: Map },
  { page: 'drivers', label: 'Motoristas', icon: Truck },
  { page: 'routes', label: 'Planejar rota', icon: Route },
  { page: 'trafegus', label: 'Trafegus', icon: Waypoints },
  { page: 'integrations', label: 'Integrações', icon: CloudSun },
  { page: 'angellira', label: 'Base AngelLira', icon: Database },
]

export function Sidebar({ page, onChange, open, onClose }: {
  page: Page
  onChange: (page: Page) => void
  open: boolean
  onClose: () => void
}) {
  return (
    <aside id="primary-navigation" className={`sidebar ${open ? 'sidebar--open' : ''}`}>
      <div className="brand">
        <div className="brand__mark"><span>7</span></div>
        <div><strong>Seven Cargo</strong><small>Central de operações</small></div>
        <button type="button" className="icon-button sidebar__close" onClick={onClose} aria-label="Fechar menu"><X size={20} /></button>
      </div>
      <nav className="nav" aria-label="Navegação principal">
        <span className="nav__eyebrow">Operação</span>
        {items.map(({ page: itemPage, label, icon: Icon }) => (
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
