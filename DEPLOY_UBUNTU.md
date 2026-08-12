# Implantação privada em Ubuntu 24.04 LTS

Este roteiro prepara uma VPS limpa para o MVP Seven Cargo. A versão só pode ser
considerada pronta após todos os itens da seção **Aceite obrigatório** passarem
na VPS real. O banco SQLite nunca faz parte da imagem Docker.

## Arquitetura

```text
Internet :80/:443
        │
      Caddy ── HTTPS automático e reverse proxy
        ├── frontend:8080 (Nginx não-root, SPA estática)
        └── backend:8000 (FastAPI/Uvicorn não-root, WebSocket)
                         │
                    ./data/operations.db
```

Somente Caddy publica portas. Backend e frontend ficam na rede Docker interna.
Caddy encaminha `/api/*`, `/tracking/*`, `/operations/*`, `/fleet/*`,
`/traffic/*`, `/routes/*` e os demais prefixos da API ao backend. As outras
rotas, inclusive `/viagem/{token}`, são entregues ao frontend com fallback SPA.

Persistem fora dos containers:

- `./data/operations.db` e sidecars SQLite transitórios;
- `./data/backups/` e respectivos manifestos;
- `./data/reports/automatic/`;
- volumes `caddy-data` e `caddy-config`, que guardam certificados e estado ACME.

Logs vão para stdout/stderr, com rotação Docker de 5 arquivos de 10 MB. Access
logs HTTP estão desativados para não registrar tokens presentes em URLs públicas.

## 1. Preparar o Ubuntu

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo adduser --disabled-password --gecos "" seven-deploy
sudo usermod -aG docker seven-deploy
```

Abra nova sessão como `seven-deploy`. Restrinja o firewall às portas 22, 80 e
443 e confirme que DNS `A/AAAA` do domínio aponta para a VPS.

## 2. Clonar e congelar a versão

```bash
sudo install -d -o seven-deploy -g seven-deploy -m 0750 /opt/seven-cargo
git clone <URL_DO_REPOSITORIO> /opt/seven-cargo/app
cd /opt/seven-cargo/app
git checkout <COMMIT_APROVADO>
git status --short
```

O status deve estar vazio. Use sempre hash ou tag aprovada, não uma branch móvel.

## 3. Configurar ambiente

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Edite somente no VPS. Substitua `tracking.example.com` pelo domínio real em
`APP_DOMAIN`, `ALLOWED_HOSTS`, `FRONTEND_ORIGINS` e `PUBLIC_TRIP_BASE_URL`.
Configure `ACME_EMAIL`, usuários, hashes, segredos e credenciais de integrações.
Nunca use valores de exemplo em homologação.

Se `PANEL_USERS_FILE` for utilizado, mantenha o JSON fora do Git, sob `data/`
(por exemplo, `/app/data/panel-users.json` dentro do container), com permissões
restritas. Não monte nem copie o `.env` original da estação de desenvolvimento.

Gere o hash administrativo sem gravar senha no histórico:

```bash
docker run --rm -it -v "$PWD:/app" -w /app python:3.12-slim-bookworm \
  sh -c 'pip install --quiet -r requirements-production.txt && python -m app.scripts.hash_panel_password'
```

Segredos devem ser aleatórios, independentes e ter ao menos 32 bytes. Nenhuma
variável `VITE_*` pode conter segredo; o frontend usa API relativa e deriva o
WebSocket do host atual.

## 4. Transferir o banco com segurança

Crie primeiro um backup consistente na origem usando a API SQLite da aplicação,
nunca `cp` diretamente sobre um banco ativo. Transfira o arquivo de backup por
canal autenticado e valide seu SHA-256 antes de instalá-lo.

```bash
install -d -m 0750 data
sha256sum <ARQUIVO_RECEBIDO>
install -m 0640 <ARQUIVO_RECEBIDO> data/operations.db.incoming
test ! -e data/operations.db
mv data/operations.db.incoming data/operations.db
sudo chown -R 10001:10001 data
```

O teste `test ! -e` impede substituir acidentalmente um banco já instalado.
Em atualizações futuras, nunca copie novamente o banco do repositório ou da
estação local. O diretório `data/` é ignorado pelo Git e montado no container.

Se não houver banco anterior, deixe `data/operations.db` ausente: somente o
serviço explícito `migrate` está autorizado a criar um banco novo.
O serviço efêmero `volume-init` também normaliza a propriedade do bind mount
para o UID/GID 10001 usado pelo backend; ele não abre o SQLite.

## 5. Validar configuração e migrar

```bash
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production build --pull
docker compose --env-file .env.production run --rm migrate
docker compose --env-file .env.production run --rm migrate
```

A migração atualiza com transação explícita até o schema 10. A segunda execução
deve ser idempotente. Se migração, integridade ou FK falhar, o container deve
terminar com erro e o backend não deve subir.

Antes de migrar um banco existente, produza e teste um backup. Nunca execute
`VACUUM`, DDL manual ou scripts destrutivos no único arquivo disponível.

## 6. Primeiro deploy

```bash
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=200 migrate backend frontend caddy
curl -fsS https://$APP_DOMAIN/health
```

Se a variável não estiver exportada no shell, substitua `$APP_DOMAIN` pelo
domínio. Caddy obtém e renova certificados automaticamente quando DNS e portas
80/443 estiverem corretos.

## 7. Backup diário

Teste manualmente:

```bash
chmod 750 scripts/backup_operations_db.sh
BACKUP_RETENTION_DAYS=14 scripts/backup_operations_db.sh
ls -la data/backups
```

O script usa a API `sqlite3.Connection.backup`, verifica integridade, cria hash e
manifesto e aplica retenção. Para execução diária:

```bash
crontab -e
```

Exemplo às 02:30:

```cron
30 2 * * * cd /opt/seven-cargo/app && BACKUP_RETENTION_DAYS=14 ./scripts/backup_operations_db.sh >>/var/log/seven-cargo-backup.log 2>&1
```

Proteja e rotacione esse log. Mantenha também cópia criptografada fora da VPS;
backup somente no mesmo disco não protege contra perda do servidor.

## 8. Operação diária

```bash
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=200 backend
docker compose --env-file .env.production logs -f caddy
docker compose --env-file .env.production restart backend
docker compose --env-file .env.production stop
docker compose --env-file .env.production start
```

Não use `docker compose down -v`: a opção `-v` remove certificados e volumes
nomeados. O banco está em bind mount, mas deve continuar protegido por backup.

## 9. Atualizar por commit específico

No PC: desenvolver, testar, criar commit e fazer push somente após aprovação.

Na VPS:

```bash
cd /opt/seven-cargo/app
git fetch --prune --tags
git status --short
git checkout <NOVO_COMMIT_APROVADO>
docker compose --env-file .env.production build --pull
docker compose --env-file .env.production run --rm migrate
docker compose --env-file .env.production up -d
docker compose --env-file .env.production ps
```

O worktree deve estar limpo antes do checkout. Faça backup consistente e valide
restauração antes de qualquer migração nova.

## 10. Rollback

Rollback de aplicação:

```bash
git checkout <COMMIT_ANTERIOR_APROVADO>
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d
```

Não reverta schema “às cegas”. Se a versão anterior for incompatível com o
schema atual, restaure em arquivo separado o backup anterior à migração,
valide integridade/FK e só então faça troca controlada com os serviços parados.

Restauração segura:

1. `docker compose stop backend migrate`;
2. preserve `data/operations.db` com nome timestampado;
3. valide hash e integridade do backup;
4. instale o backup como `data/operations.db`;
5. execute `migrate` quando compatível;
6. suba e valide todas as funções abaixo.

## Aceite obrigatório na VPS

- [ ] `docker compose config --quiet` passa sem warnings relevantes.
- [ ] imagens constroem do zero com `--pull`.
- [ ] containers de aplicação rodam sem root e sem `privileged`.
- [ ] somente 80/tcp, 443/tcp e 443/udp estão publicados.
- [ ] Caddy emite certificado válido e redireciona HTTP para HTTPS.
- [ ] `/health` retorna 200 pelo domínio e backend não fica público em `:8000`.
- [ ] migração 9→10 preserva dados; segunda execução não altera dados/hash lógico.
- [ ] falha de migração impede a subida do backend.
- [ ] startup não altera `sqlite_master`, `schema_version` ou dados.
- [ ] login, logout e replay de cookie funcionam como esperado.
- [ ] CORS aceita somente o domínio HTTPS configurado.
- [ ] Trafegus funciona apenas em leitura e mantém modo degradado em falha.
- [ ] TomTom/OpenWeather habilitados respondem sem segredos nos logs.
- [ ] WebSocket conecta por `wss://<domínio>/tracking/ws/manager`.
- [ ] link público abre em `/viagem/{token}` por rede 4G.
- [ ] PDF baixa, começa com `%PDF-` e abre normalmente.
- [ ] backup diário gera SQLite íntegro, manifesto e retenção correta.
- [ ] restauração foi testada em arquivo/volume separado.
- [ ] `docker compose logs` não contém senhas, cookies ou tokens completos.
- [ ] reinício e recriação de containers preservam banco, relatórios e Caddy.

Até essa lista ser executada em Ubuntu/Docker real, a versão não está aprovada
para produção.
