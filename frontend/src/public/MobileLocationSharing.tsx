import { AlertTriangle, MapPinned, Play, Square, X } from 'lucide-react'
import { useMobileLocation } from './hooks/useMobileLocation'

export function MobileLocationSharing({ token, enabled }: { token: string; enabled: boolean }) {
  const sharing = useMobileLocation(token, enabled)
  if (!enabled) return <section className="public-card public-sharing" aria-labelledby="sharing-title">
    <MapPinned /><div><span>Compartilhamento pelo celular</span><h2 id="sharing-title">Não habilitado nesta viagem</h2><p>O rastreador do veículo continua sendo a fonte principal.</p></div><span className="public-sharing-badge">Inativo</span>
  </section>
  return <>
    <section className="public-card public-sharing" aria-labelledby="sharing-title">
      <MapPinned /><div><span>Compartilhamento pelo celular</span><h2 id="sharing-title">{sharingLabel(sharing.status)}</h2><p>{sharing.message || 'O GPS do celular é apenas complementar. O rastreador do veículo continua sendo a fonte principal.'}</p><small>A página deverá permanecer aberta. O navegador pode suspender a localização quando a tela estiver bloqueada ou minimizada.</small></div>
      {sharing.status === 'sharing'
        ? <button type="button" className="public-secondary-action" onClick={sharing.stop}><Square /> Interromper</button>
        : <button type="button" className="public-secondary-action" onClick={sharing.requestConsent}><Play /> Compartilhar</button>}
    </section>
    {sharing.status === 'consent' && <div className="public-consent-backdrop" role="presentation">
      <section className="public-consent" role="dialog" aria-modal="true" aria-labelledby="mobile-consent-title">
        <button className="public-consent-close" onClick={sharing.stop} aria-label="Fechar"><X /></button>
        <AlertTriangle /><h2 id="mobile-consent-title">Compartilhar localização do celular?</h2>
        <ul><li>Serão enviados latitude, longitude, precisão e horário durante esta viagem.</li><li>O compartilhamento depende da sua autorização e pode ser interrompido a qualquer momento.</li><li>A página deve permanecer aberta; tela bloqueada ou navegador minimizado podem suspender o GPS.</li><li>O link deixa de aceitar posições quando expira, é revogado ou a viagem termina.</li></ul>
        <p>Não tente usar o aparelho enquanto estiver dirigindo. Inicie somente com o veículo parado e em segurança.</p>
        <button className="public-consent-confirm" onClick={sharing.start}>Entendi e quero compartilhar</button>
      </section>
    </div>}
  </>
}

function sharingLabel(status: string): string {
  return ({ idle: 'Não iniciado', consent: 'Aguardando autorização', sharing: 'Compartilhando', denied: 'Permissão recusada', unavailable: 'GPS indisponível', stopped: 'Interrompido', error: 'Envio temporariamente interrompido' } as Record<string, string>)[status] || 'Não iniciado'
}
