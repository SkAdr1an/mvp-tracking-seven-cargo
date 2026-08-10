import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../api'

export function PanelGate({children,onConnection}:{children:ReactNode;onConnection?:(state:'connected'|'disconnected')=>void}) {
  const [ready,setReady]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('')
  const [username,setUsername]=useState(''),[password,setPassword]=useState('')
  useEffect(()=>{api.panelMe().then(()=>{setReady(true);onConnection?.('connected')}).catch(error=>{setReady(false);onConnection?.(error instanceof Error&&error.message.toLowerCase().includes('sessão')?'connected':'disconnected')}).finally(()=>setLoading(false))},[onConnection])
  if(loading)return <section className="panel history-empty">Validando acesso…</section>
  if(ready)return <>{children}</>
  return <section className="panel admin-gate"><div><span className="eyebrow">Acesso protegido</span><h2>Entre para consultar dados de motoristas</h2><p>Histórico, avaliações e relatórios exigem uma sessão autorizada.</p></div><form onSubmit={async event=>{event.preventDefault();setError('');try{await api.panelLogin({username,password});setReady(true)}catch(reason){setError(reason instanceof Error?reason.message:'Falha ao entrar')}}}><input aria-label="Usuário" placeholder="Usuário" value={username} onChange={event=>setUsername(event.target.value)}/><input aria-label="Senha" placeholder="Senha" type="password" value={password} onChange={event=>setPassword(event.target.value)}/><button className="primary-button">Entrar</button>{error&&<span className="form-error">{error}</span>}</form></section>
}
