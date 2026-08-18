# Estado consolidado do desenvolvimento

Data da consolidação: 2026-08-18  
Branch local: `develop/full-current`  
Worktree: `.runtime/feature-worktrees/full-current`  
Base anterior: `759a1de`  
SHA de integração anterior a este documento: `ed0b2a0`

Esta branch reúne as fases já commitadas da release conservadora, o desenvolvimento local corrente, o histórico e as avaliações de motoristas, a Auditoria modular e a seleção segura do stash preservado. Nenhum deploy ou push faz parte desta consolidação.

## FUNCIONANDO

- Dashboard/Visão geral com métricas operacionais, filtros, mapa, progresso e estados degradados seguros.
- Planejamento de rota com catálogo persistido, geometria, pontos obrigatórios, simulação e calculadora de custos.
- Tráfego por múltiplas rotas com BBOX segmentado, deduplicação, corredor adaptativo, cooldown e expiração de incidentes irrelevantes.
- TomTom com fallback para Azure Maps Traffic, categorias normalizadas, health e exposição na tela Integrações.
- OpenWeather desacoplado de `FLEET_ROUTING_ENABLED`, usando geometria persistida, cache e amostragem de rota.
- Histórico de motoristas, avaliações pendentes, ajustes de pontualidade, vínculo manual de identidade e relatório em PDF.
- RBAC persistente, gestão de usuários, contraste dos botões e Auditoria central modular.
- Ciclo de viagens com cancelamento, arquivamento e reabertura auditáveis.
- Login cinematográfico com chuva, leão, mapa, caminhão e identidade visual Seven Cargo.
- Portal público/mobile e integrações operacionais já presentes na base.

## EM DESENVOLVIMENTO

- A operação real dos provedores externos depende das credenciais e da disponibilidade de cada serviço no ambiente de execução.
- O histórico de motoristas depende da sincronização/backfill operacional controlado para popular dados legados; consultas vazias não inventam nem fazem backfill implícito.
- A geometria ausente de uma rota é reportada como estado degradado, sem recorrer ao antigo hardcode Betim–Jaboatão.

## PRECISA DE REVISÃO

- Exclusão permanente de usuário: a implementação exige a senha separada do criador e preserva autoria/histórico por tombstone antes de remover credenciais, sessões e a identidade ativa. Ela não apaga eventos, observações ou histórico relacionado. Ainda assim, por conter `DELETE FROM users`, deve passar por revisão operacional e teste em cópia descartável do banco antes de qualquer habilitação em produção.
- O pacote npm instalado informou duas vulnerabilidades de severidade alta em dependências. Não foi executado `npm audit fix`, para evitar atualização automática fora do escopo da consolidação.
- A inspeção visual automatizada confirmou o login. As telas autenticadas foram cobertas por build, lint e testes funcionais/componentes, mas ainda merecem uma rodada humana completa com perfis ADMIN, GR e MONITORING antes de release.

## PENDENTE DE DEPLOY

- Toda esta branch. Nenhum commit foi enviado e nenhuma alteração foi aplicada ao VPS.
- Validar uma cópia do banco real com a cadeia de migrações antes de preparar release.
- Confirmar variáveis de ambiente de TomTom, Azure Maps, OpenWeather, Trafegus e autenticação no processo formal de release, sem registrá-las no Git.

## Migrações consolidadas

- `009_driver_history_evaluations.sql`: histórico e avaliações de motoristas; aditiva e com rollback restrito a banco descartável.
- `010_journey_observation.sql`: observação de jornada já legítima na base.
- `011_persistent_users_rbac.sql`: usuários e RBAC persistentes.
- `012_operational_observations.sql`: observações operacionais imutáveis/corrigíveis.
- `013_central_audit_log.sql`: esquema oficial da Auditoria central.
- `014_trip_cancel_archive.sql`: ciclo de cancelamento e arquivamento.

O arquivo obsoleto `migrations/010_audit_events.sql` não foi incorporado.

## Validação executada

- Backend: `406 passed`, `28 skipped`.
- Frontend: `105 passed`.
- ESLint: aprovado.
- TypeScript + Vite build: aprovado.
- `compileall`: aprovado.
- Login local em 1440×1000: carregado e inspecionado com os assets cinematográficos.
