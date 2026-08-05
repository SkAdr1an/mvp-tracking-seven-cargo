import { MapPinned, Play, Square } from 'lucide-react'
import { useMobileLocation } from './hooks/useMobileLocation'

export function MobileLocationSharing({ token, enabled }: { token: string; enabled: boolean }) {
  const sharing = useMobileLocation(token, enabled)
  if (!enabled) return <section className="public-card public-sharing" aria-labelledby="sharing-title">
    <MapPinned /><div><span>Compartilhamento pelo celular</span><h2 id="sharing-title">Não habilitado nesta viagem</h2><p>O rastreador do veículo continua sendo a fonte principal.</p></div><span className="public-sharing-badge">Inativo</span>
  </section>
  return <>
    <section className="public-card public-sharing" aria-labelledby="sharing-title">
      <MapPinned /><div><span>Compartilhamento pelo celular</span><h2 id="sharing-title">{sharingLabel(sharing.status)}</h2><p>{sharing.message || 'O GPS do celular é complementar. O rastreador do veículo continua sendo a fonte principal.'}</p></div>
      {sharing.status === 'sharing'
        ? <button type="button" className="public-secondary-action" onClick={sharing.stop}><Square /> Interromper</button>
        : <button type="button" className="public-secondary-action" onClick={sharing.start}><Play /> Compartilhar localização</button>}
    </section>
  </>
}

function sharingLabel(status: string): string {
  return ({ idle: 'Não iniciado', sharing: 'Compartilhando', denied: 'Permissão recusada', unavailable: 'GPS indisponível', stopped: 'Interrompido', error: 'Envio temporariamente interrompido' } as Record<string, string>)[status] || 'Não iniciado'
}
