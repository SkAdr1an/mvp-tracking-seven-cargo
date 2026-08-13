import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { usePermission } from '../permissions'
import type { ManagedUser } from '../types'

const roleLabels={ADMIN:'Administrador',GR:'GR',MONITORING:'Monitoramento'}

export function UsersAdmin(){
  const client=useQueryClient();const query=useQuery({queryKey:['users'],queryFn:api.users})
  const canManage=usePermission('users:manage')
  const [form,setForm]=useState({display_name:'',username:'',role:'MONITORING',password:'',confirm:''})
  const [error,setError]=useState('')
  const refresh=()=>client.invalidateQueries({queryKey:['users']})
  const create=useMutation({mutationFn:api.createUser,onSuccess:()=>{void refresh();setForm({display_name:'',username:'',role:'MONITORING',password:'',confirm:''})},onError:(e)=>setError(e.message)})
  const submit=(event:React.FormEvent)=>{event.preventDefault();setError('');if(form.password!==form.confirm){setError('As senhas não coincidem.');return}create.mutate(form)}
  return <div className="page-stack users-admin"><div className="section-heading"><div><span className="eyebrow">Acesso persistente</span><h2>Usuários</h2><p>Cadastre e gerencie os três perfis oficiais sem excluir o histórico.</p></div></div>
    {canManage&&<form className="panel user-form" onSubmit={submit}><h3>Novo usuário</h3><label>Nome completo<input value={form.display_name} onChange={e=>setForm({...form,display_name:e.target.value})} required/></label><label>Usuário<input value={form.username} onChange={e=>setForm({...form,username:e.target.value})} required/></label><label>Perfil<select value={form.role} onChange={e=>setForm({...form,role:e.target.value})}><option value="ADMIN">Administrador</option><option value="GR">GR</option><option value="MONITORING">Monitoramento</option></select></label><label>Senha inicial<input type="password" minLength={12} value={form.password} onChange={e=>setForm({...form,password:e.target.value})} required/></label><label>Confirmar senha<input type="password" minLength={12} value={form.confirm} onChange={e=>setForm({...form,confirm:e.target.value})} required/></label>{error&&<div className="form-error" role="alert">{error}</div>}<button disabled={create.isPending}>{create.isPending?'Criando...':'Criar usuário'}</button></form>}
    <section className="panel"><h3>Contas cadastradas</h3>{query.isLoading?<p>Carregando...</p>:query.isError?<p className="form-error">{query.error.message}</p>:<div className="user-list">{query.data?.users.map(user=><UserRow key={user.id} user={user} refresh={refresh} canManage={canManage}/>)}</div>}</section>
  </div>
}

function UserRow({user,refresh,canManage}:{user:ManagedUser;refresh:()=>Promise<unknown>;canManage:boolean}){
  const [error,setError]=useState('');const mutate=useMutation({mutationFn:async(action:'status'|'role'|'password')=>{if(action==='status')return api.setUserActive(user.id,user.status!=='ACTIVE');if(action==='role'){const role=window.prompt('Novo perfil: ADMIN, GR ou MONITORING',user.role);if(!role)return;return api.updateUser(user.id,{role})}const password=window.prompt('Nova senha (mínimo 12 caracteres)');if(!password)return;return api.resetUserPassword(user.id,password)},onSuccess:()=>void refresh(),onError:e=>setError(e.message)})
  return <article className="user-row"><div><strong>{user.display_name}</strong><span>@{user.username} · {roleLabels[user.role]}</span><small>{user.status==='ACTIVE'?'Ativo':'Inativo'} · atualizado em {new Date(user.updated_at).toLocaleString('pt-BR')}</small></div>{canManage&&<div><button onClick={()=>mutate.mutate('role')}>Alterar perfil</button><button onClick={()=>mutate.mutate('password')}>Redefinir senha</button><button onClick={()=>mutate.mutate('status')}>{user.status==='ACTIVE'?'Inativar':'Ativar'}</button></div>}{error&&<small className="form-error">{error}</small>}</article>
}
