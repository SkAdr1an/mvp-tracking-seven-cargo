import { Bell, LogOut, Menu, RefreshCw } from 'lucide-react'
import type { Page } from '../types'

const titles: Record<Page, [string, string]> = {
  overview: ['Visão geral', 'Acompanhe sua operação em tempo real'],
  drivers: ['Motoristas', 'Localização e telemetria da equipe'],
  routes: ['Planejamento de rota', 'Previsão de distância, trânsito e chegada'],
  trafegus: ['Consulta Trafegus', 'Veículo, posição, eventos e viagem'],
  integrations: ['Integrações', 'Saúde dos serviços conectados'],
  angellira: ['Base AngelLira', 'Referências homologadas e filas de revisão'],
}

export function Header({ page, connection, menuOpen, attentionCount, criticalCount, username, role, onLogout, onMenu, onReconnect }: {
  page: Page
  connection: 'connecting' | 'connected' | 'disconnected'
  menuOpen: boolean
  attentionCount: number
  criticalCount: number
  username: string
  role: string
  onLogout: () => Promise<void>
  onMenu: () => void
  onReconnect: () => void
}) {
  const [title, subtitle] = titles[page]
  return (
    <header className="topbar">
      <button className="icon-button menu-button" onClick={onMenu} aria-label="Abrir menu" aria-expanded={menuOpen} aria-controls="primary-navigation"><Menu size={21} /></button>
      <div className="topbar__title"><h1>{title}</h1><p>{subtitle}</p></div>
      <div className="topbar__actions">
        <div className="topbar__alerts" aria-label="Resumo de alertas">
          <span className="topbar__alert topbar__alert--attention"><b>{attentionCount}</b> Atenção</span>
          <span className="topbar__alert topbar__alert--critical"><b>{criticalCount}</b> Críticas</span>
        </div>
        <button className={`connection connection--${connection}`} onClick={connection === 'disconnected' ? onReconnect : undefined}>
          <span className="connection__dot" />
          {connection === 'connected' ? 'Tempo real' : connection === 'connecting' ? 'Conectando' : 'Reconectar'}
          {connection === 'disconnected' && <RefreshCw size={14} />}
        </button>
        <button className="icon-button" aria-label="Notificações"><Bell size={20} /><span className="notification-dot" /></button>
        <div className="topbar__identity"><span>{username}</span><small>{role}</small></div>
        <button className="icon-button" onClick={() => void onLogout()} aria-label="Sair"><LogOut size={20}/></button>
      </div>
    </header>
  )
}
