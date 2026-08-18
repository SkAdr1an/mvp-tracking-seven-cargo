interface ProfileBadgeProps { role?: string | null }
const knownRoles: Record<string,string>={ADMIN:'Admin',GR:'GR',MONITORING:'Monitoramento',UNKNOWN:'Desconhecido'}
export function ProfileBadge({role}:ProfileBadgeProps){const normalized=role?.toUpperCase()||'UNKNOWN';const modifier=Object.hasOwn(knownRoles,normalized)?normalized.toLowerCase():'unknown';return <span className={`profile-badge profile-badge--${modifier}`} title={`Perfil: ${role||'Desconhecido'}`}><span aria-hidden="true" className="profile-badge__dot"/>{knownRoles[normalized]||role}</span>}
