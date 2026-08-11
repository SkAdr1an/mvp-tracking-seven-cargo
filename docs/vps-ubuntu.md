# Execução controlada em VPS Ubuntu

## Pré-requisitos

- Ubuntu LTS com Docker Engine e Compose v2;
- DNS apontando para a VPS;
- certificado TLS com `fullchain.pem` e `privkey.pem`;
- firewall expondo somente 22, 80 e 443;
- diretório externo e criptografado para cópias de segurança.

O backend não publica porta no host. Todo acesso passa pelo Nginx em HTTPS.
Somente um worker Uvicorn é iniciado, pois SQLite, cache e WebSockets ainda são
locais ao processo.

## Configuração inicial

1. Copie `.env.example` para um arquivo fora do repositório, com permissão 600.
2. Gere o hash da senha sem escrevê-la no histórico do shell:

   `python -m app.scripts.hash_panel_password`

3. Preencha `PANEL_ADMIN_PASSWORD_HASH`, uma chave aleatória de pelo menos 32
   bytes em `PANEL_SESSION_SECRET` e outra em `PUBLIC_TRIP_TOKEN_PEPPER`.
   Como alternativa para múltiplos usuários, monte um JSON externo e configure
   `PANEL_USERS_FILE`. Cada entrada deve conter apenas `username`,
   `password_hash`, `role` e `active`; nunca senha em texto claro.
4. Configure `APP_DOMAIN`, `TLS_DIRECTORY`, `ALLOWED_HOSTS` e apenas a origem
   HTTPS exata em `FRONTEND_ORIGINS`.
5. Configure somente as integrações aprovadas. Nunca coloque segredos no
   Dockerfile, Compose ou argumentos de build.

Perfis diferentes de Administrador permanecem bloqueados até aprovação da
matriz em `docs/permission-matrix.md`.

## Validação e subida

```sh
docker compose --env-file /etc/seven-cargo/panel.env config
APP_ENV_FILE=/etc/seven-cargo/panel.env docker compose build
APP_ENV_FILE=/etc/seven-cargo/panel.env docker compose run --rm migrate
APP_ENV_FILE=/etc/seven-cargo/panel.env docker compose up -d
docker compose ps
```

O serviço `migrate` executa as alterações idempotentes antes do backend. Antes
de qualquer nova migração em ambiente com dados, faça backup consistente e
teste a restauração. Não execute SQL manual diretamente no volume.

## Backup e restauração

Crie backups pelo mecanismo SQLite da aplicação:

```sh
docker compose exec backend python -m app.scripts.backup_operations \
  --directory /app/data/backups --label manual
```

Copie banco e manifesto para armazenamento externo criptografado. Para
restaurar, pare backend e `migrate`, preserve o arquivo atual, coloque a cópia
validada no volume e execute `PRAGMA integrity_check` e
`PRAGMA foreign_key_check` antes de subir. Valide healthcheck, login e contagens
operacionais após a restauração.

## Operação

- Configure rotação no driver de logs do Docker ou no agente da VPS.
- Monitore saúde, espaço do volume, idade do último backup e falhas das APIs.
- O Chromium e fontes básicas são instalados na imagem para PDF em Linux.
- Atualizações devem usar imagem identificada pelo hash Git e nunca editar o
  container em execução.
- Rollback da aplicação: suba a imagem anterior sem reverter o banco às cegas.
  Se uma migração incompatível tiver ocorrido, restaure o backup anterior.
