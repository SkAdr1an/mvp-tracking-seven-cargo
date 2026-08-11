# Matriz inicial de permissões

Esta matriz aplica menor privilégio enquanto a Seven Cargo não aprova a
distribuição funcional definitiva. Perfis sem decisão administrativa permanecem
sem acesso; a aplicação responde `403` quando um usuário autenticado com esses
perfis tenta acessar um módulo protegido.

| Módulo ou ação | Administrador | Gestor | Operacional | Tracking | Cadastro | Financeiro | Consulta |
|---|---:|---:|---:|---:|---:|---:|---:|
| Painel e indicadores | Permitido | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária |
| Viagens, rotas e motoristas | Permitido | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária |
| Trafegus, TomTom, clima e ORS | Permitido | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária |
| Ocorrências e monitoramento | Permitido | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária |
| Alterações operacionais | Permitido | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária |
| Links públicos e relatórios | Permitido | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária |
| Base AngelLira e cadastros | Permitido | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária | Decisão necessária |
| Administração de usuários | Permitido | Negado | Negado | Negado | Negado | Negado | Negado |

O token técnico de tracking não representa um usuário do perfil `Tracking`.
Ele permanece uma credencial máquina-a-máquina limitada aos endpoints
`/tracking`, sem conceder sessão no painel.
