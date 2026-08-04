import { AlertTriangle, CloudRain, Construction, MapPin, Route, ShieldAlert } from 'lucide-react'
import type { PortalAlertsResponse } from './types'
import { locationAgeLabel } from './portalUtils'

export function PortalAlerts({ data, degraded }: { data?: PortalAlertsResponse; degraded: boolean }) {
  const alerts = data?.alerts || []
  const integrationDegraded = Object.values(data?.integrations || {}).some((value) => !['OPERATIONAL', 'CONNECTED'].includes(value))
  return <section className="public-card public-alerts" aria-labelledby="portal-alerts-title">
    <header><AlertTriangle /><div><span>Segurança no trajeto</span><h2 id="portal-alerts-title">Próximos alertas</h2></div></header>
    {(degraded || integrationDegraded) && <p className="public-alerts-degraded">Parte das informações de trânsito ou clima está indisponível. Os dados válidos restantes foram preservados.</p>}
    {alerts.length === 0 ? <p>Nenhum alerta confiável à frente neste momento.</p> : <div className="public-alert-list">{alerts.map((alert) => <article key={alert.id} className={`public-alert public-alert--${alert.severity.toLowerCase()}`}><i>{alertIcon(alert.type)}</i><div><div className="public-alert-heading"><strong>{alertTitle(alert.type)}</strong><span>{alert.distance_km != null ? `aprox. ${formatDistance(alert.distance_km)}` : 'distância indisponível'}</span></div><p>{alert.description}{alert.delay_minutes != null ? ` Acréscimo estimado de ${Math.round(alert.delay_minutes)} minutos.` : ''}</p><small>{alert.reference || 'Referência indisponível'} · {alert.source} · {locationAgeLabel(alert.updated_at)}</small><em>{alert.guidance}</em></div></article>)}</div>}
    <footer>Consulte os alertas somente com o veículo parado em local seguro.</footer>
  </section>
}

function alertIcon(type: string) { if (type.includes('CHUVA')) return <CloudRain />; if (type === 'DESVIO_CONFIRMADO') return <Route />; if (type === 'DESTINO' || type === 'ORIGEM') return <MapPin />; if (type === 'TRANSITO_LENTO') return <Construction />; return <ShieldAlert /> }
function alertTitle(type: string) { return ({ TRANSITO_LENTO: 'Trânsito lento', ACIDENTE_BLOQUEIO: 'Acidente ou bloqueio', CHUVA_LEVE: 'Chuva leve', CHUVA_FORTE: 'Chuva forte ou temporal', DESVIO_CONFIRMADO: 'Desvio confirmado', DESTINO: 'Aproximação do destino', ORIGEM: 'Aproximação da origem' } as Record<string, string>)[type] || 'Obstáculo à frente' }
function formatDistance(km: number) { return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} km` }
