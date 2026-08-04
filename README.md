# 7Seven Cargo — Tracking operacional

MVP FastAPI + React para acompanhar viagens do Trafegus, calcular ETA com a
TomTom, identificar riscos meteorológicos e controlar localmente os estados de
origem/destino. O sistema nunca altera nem encerra viagens no Trafegus.

## Mapa operacional e Traffic API

A Visão Geral usa React Leaflet/Leaflet sobre tiles OpenStreetMap. A chave TomTom
permanece somente no backend. O mapa combina caminhões, geometria operacional,
origem/destino, cercas, riscos climáticos, ocorrências manuais e incidentes reais
da TomTom Traffic Incident Details v5. O Flow Segment Data v4 é monitorado
separadamente para saúde e diagnóstico de fluxo.

O coletor de trânsito roda sem o dashboard. Ele projeta os caminhões na geometria
da rota, densifica os pontos de controle e consulta apenas áreas entre a posição
mais recuada e o horizonte configurado à frente. Cada área tem menos de 10.000
km²; resultados sobrepostos são deduplicados pelo ID TomTom e filtrados novamente
pelo corredor. Com espaçamento de 60 km e horizonte de 350 km, o consumo típico é
de até 12 chamadas de Incident Details por ciclo, priorizadas pela proximidade à
frente dos veículos, mais uma chamada Flow. Sem caminhões associados, não há
varredura do corredor.

O atraso de uma ocorrência é apenas informativo: o ETA de Routing já incorpora
tráfego e `eta_adjustment_applied=false` impede dupla contagem.

## Fluxo

1. Um coletor de background consulta posições, viagens e o vínculo atual do
   veículo no Trafegus a cada 60 segundos.
2. A associação atual do veículo é comparada ao motorista da viagem. Um vínculo
   atual único é priorizado; dados ambíguos preservam o último vínculo confiável
   e geram o aviso `Divergência de condutor`.
3. Toda posição, seja do Trafegus ou do WebSocket, passa pelo mesmo processador
   de cercas e estados.
4. O estado, as posições necessárias à decisão e o histórico são persistidos em
   SQLite. A camada `OperationsRepository` isola o banco para futura migração a
   PostgreSQL.

## Configuração

Crie `.env` a partir de `.env.example`. As variáveis operacionais principais são:

- `OPERATIONS_DATABASE_PATH`: banco SQLite; padrão `data/operations.db`.
- `FLEET_COLLECTOR_ENABLED`: ativa o processamento sem depender do dashboard.
- `FLEET_COLLECTOR_INTERVAL_SECONDS`: intervalo de coleta; padrão 60 segundos.
- `RETURN_MIN_DESTINATION_STAY_HOURS`: permanência mínima em Jaboatão antes de considerar um possível retorno; padrão 18 horas.
- `RETURN_MIN_PROGRESS_KM`: avanço mínimo em direção a Betim; padrão 40 km.
- `RETURN_DIRECTION_READINGS`: leituras consecutivas exigidas na direção de Betim; padrão 3.
- `RETURN_CORRIDOR_M`: distância máxima da geometria oficial para a detecção; padrão 1.000 m.
- `TRACKING_API_KEY`: token dos endpoints e WebSockets próprios de rastreamento.
- `TRAFFIC_COLLECTOR_INTERVAL_SECONDS`: intervalo do coletor; padrão 180 segundos.
- `TRAFFIC_CORRIDOR_KM`: distância máxima da ocorrência à geometria; padrão 15 km.
- `TRAFFIC_LOOKAHEAD_KM`: horizonte consultado à frente; padrão 350 km.
- `TRAFFIC_QUERY_SPACING_KM`: espaçamento das áreas; padrão 60 km.
- `TRAFFIC_MAX_INCIDENT_CALLS_PER_CYCLE`: teto de consultas Incidents; padrão 12.
- `TRAFEGUS_*`, `TOMTOM_API_KEY` e `OPENWEATHER_API_KEY`: integrações externas.

Credenciais, tokens, documentos e respostas brutas não devem ser versionados.

## Reconhecimento de retorno

Uma ida finalizada não permanece ativa apenas porque o rastreador continua
transmitindo. O sistema reutiliza as posições do coletor e só apresenta
“Possível retorno” depois da permanência mínima no destino, saída confirmada da
cerca, três avanços consecutivos em direção a Betim, distância mínima e
compatibilidade com o corredor oficial.

O operador responde **Sim**, **Não** ou **Verificar depois**. “Sim” cria uma
viagem separada Jaboatão → Betim usando a geometria oficial invertida; “Não”
classifica o deslocamento como externo e suspende alertas operacionais;
“Verificar depois” mantém apenas a pendência, sem desvio ou criticidade. A
decisão, o usuário, os horários e as evidências resumidas ficam auditados no
SQLite. Nenhuma chamada adicional é feita ao Trafegus e a integração continua
somente leitura.

## Diagnóstico operacional e ETA dinâmico

O perfil individual na aba **Motoristas** apresenta um diagnóstico calculado no
mesmo ciclo do snapshot coletivo. Abrir ou fechar o painel não dispara consultas
ao Trafegus, TomTom ou OpenWeather.

O ETA combina o tempo de percurso TomTom, a distância restante projetada na
geometria oficial, posição e idade do sinal, margem operacional proporcional,
parada prolongada fora de local esperado, trânsito, clima, desvio e distância
estimada para retornar à rota. A velocidade instantânea nunca é usada
isoladamente.

São persistidos o ETA provável, janela otimista/conservadora, compromisso do
cliente, tendência, confiança, fatores, riscos, recomendações, método e último
resultado confiável. Posições antigas, falhas temporárias e dados insuficientes
preservam o último ETA confiável. Variações inferiores a dez minutos são
estabilizadas quando classificação e riscos não mudaram.

Viagens encerradas e possíveis retornos ainda não confirmados não recebem ETA
operacional. Um retorno Seven confirmado utiliza sua própria viagem e a
geometria Jaboatão → Betim, sem misturar o histórico da ida.

## Rota e cercas

As rotas ficam em `route_configs` e suportam raios, permanência, velocidade de
parada, SLA e ativação independentes. A primeira rota é:

- Betim/MG → Jaboatão dos Guararapes/PE
- Origem: `-19.981871, -44.2666224` — SOC_MG_BETIM SHOPEE, Av. das Palmeiras, 347.
- Destino: `-8.2098931, -34.9636963` — coordenada resolvida do link operacional.
- Raio de entrada: 500 m.
- Raio de saída/histerese: 650 m.
- Confirmação: duas leituras consecutivas.
- Permanência mínima: 10 minutos.
- Velocidade máxima de confirmação no destino: 5 km/h.
- Finalização local: 30 minutos confirmados no destino.

Os valores são registros configuráveis, não condicionais fixas no motor.

## Máquina de estados

`PROGRAMADA → NA_ORIGEM → EM_CARREGAMENTO → EM_VIAGEM → NO_DESTINO → FINALIZADA_NO_SISTEMA`

Uma viagem também pode assumir `REABERTA_MANUALMENTE`. Ações manuais de
correção, finalização, reabertura e desfazer detecção exigem justificativa e são
auditadas. A finalização automática ou manual ocorre apenas no SQLite local.

As proteções incluem fingerprint de posição, ordenação temporal, leituras
consecutivas, permanência mínima, velocidade de parada, histerese e chaves de
idempotência para eventos.

## API

Endpoints existentes permanecem compatíveis:

- `GET /health`
- `GET /fleet/active`
- `POST /routes/preview`
- `POST /trafegus/vehicles/consult`
- `/tracking/*`

Endpoints operacionais:

- `GET /operations/routes`
- `GET /operations/trips/{trip_key}`
- `GET|PUT /operations/trips/{trip_key}/plan`
- `GET /operations/trips/{trip_key}/eta-history`
- `GET /operations/trips/{trip_key}/report-data`
- `POST /operations/trips/{trip_key}/report`
- `GET /operations/exceptions`
- `POST /operations/stops/{stop_id}/justification`
- `POST /operations/trips/{trip_key}/route`
- `POST /operations/trips/{trip_key}/actions`
- `GET /traffic/incidents?route_id=...&bbox=minLon,minLat,maxLon,maxLat`
- `GET /traffic/incidents/{id}`
- `GET /traffic/incidents/{id}/vehicles`
- `POST /traffic/manual`
- `PATCH /traffic/manual/{id}`
- `GET /traffic/health`

Exemplo de ação manual:

```json
{
  "action": "reopen",
  "justification": "Finalização anterior confirmada como incorreta",
  "operator": "operador-1"
}
```

O endpoint de ações aceita `finalize`, `reopen`, `undo_detection` e
`correct_times`. Horários são armazenados em UTC e o dashboard os apresenta em
`America/Sao_Paulo`.

Paradas observadas e lacunas de comunicação ficam separadas: uma lacuna nunca é
convertida em parada presumida. O relatório final preserva plano, histórico de
ETA, eventos, posições e justificativas em HTML legível e JSON de evidência. Ele
é gerado automaticamente quando a viagem é finalizada e também pode ser
regenerado pelo endpoint autenticado.

O banco recebe backup SQLite consistente em segundo plano, com validação de
integridade, hash SHA-256, manifesto e retenção diária/semanal/mensal. O arquivo
original é aberto somente para leitura durante a cópia.

## Execução

### Forma recomendada no Windows

Use o gerenciador na raiz do projeto. No primeiro uso ele prepara as
dependências automaticamente; nas execuções seguintes, basta iniciar:

```powershell
.\project.cmd start
```

Comandos disponíveis:

```powershell
.\project.cmd status   # mostra backend, frontend e Trafegus
.\project.cmd restart  # reinicia os dois serviços
.\project.cmd stop     # encerra os dois serviços
.\project.cmd setup    # instala/atualiza dependências
.\project.cmd backup   # cria, valida e aplica retenção ao backup do banco
```

O comando `start` testa a conexão HTTPS do Trafegus e valida uma consulta real
em `/fleet/active`. O projeto somente é anunciado como pronto quando backend,
frontend e Trafegus respondem. Os logs ficam em `.runtime/`.

### Execução manual

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### Portal público da viagem

No computador, mantenha os valores de desenvolvimento:

```env
# frontend/.env
VITE_API_URL=http://192.168.18.217:8000
VITE_WS_URL=ws://192.168.18.217:8000
VITE_PUBLIC_APP_URL=http://192.168.18.217:5173

# .env
PUBLIC_TRIP_BASE_URL=http://192.168.18.217:5173/viagem
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://192.168.18.217:5173
```

Inicie o backend e o frontend normalmente. O link gerado pelo painel terá o
formato `http://192.168.18.217:5173/viagem/{token}`. A rota pública
`GET /api/public/trips/{token}` não exige autenticação.

Para testar em um celular na mesma rede Wi-Fi, descubra o IPv4 do computador
com `ipconfig` e substitua `IP_DO_COMPUTADOR` somente nos arquivos de ambiente:

```env
# frontend/.env
VITE_API_URL=http://IP_DO_COMPUTADOR:8000
VITE_PUBLIC_APP_URL=http://IP_DO_COMPUTADOR:5173

# .env
PUBLIC_TRIP_BASE_URL=http://IP_DO_COMPUTADOR:5173/viagem
FRONTEND_ORIGINS=http://IP_DO_COMPUTADOR:5173,http://localhost:5173
```

Reinicie os dois processos após alterar variáveis Vite ou backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
cd frontend
npm.cmd run dev -- --host 0.0.0.0
```

O Vite lê `frontend/.env` somente ao iniciar. Depois de qualquer alteração
nesse arquivo, encerre e inicie novamente o processo de desenvolvimento.

O service worker do Portal da Viagem fica desativado em desenvolvimento e não
armazena respostas de `/api/public/trips/`. Para limpar uma instalação anterior
no celular, abra as configurações do navegador, entre em **Configurações do
site**, selecione `192.168.18.217` e use **Limpar e redefinir**. No Chrome
desktop, use DevTools → Application → Service Workers → Unregister e
Application → Storage → Clear site data.

Abra no celular a URL gerada com o IPv4. Não use `localhost` no celular:
nesse dispositivo ele aponta para o próprio telefone. Firewall do Windows e
isolamento de clientes do roteador também precisam permitir as portas 5173 e
8000.

O Firewall não é alterado pela aplicação. Se a rede não usar isolamento entre
clientes e o celular ainda não conectar, um administrador pode liberar
opcionalmente as portas:

```powershell
netsh advfirewall firewall add rule name="Seven Cargo Frontend 5173" dir=in action=allow protocol=TCP localport=5173
netsh advfirewall firewall add rule name="Seven Cargo Backend 8000" dir=in action=allow protocol=TCP localport=8000
```

Em outro terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Validação

```powershell
python -m pytest -q
cd frontend
npm run lint
npm run build
```

Os testes cobrem cercas, permanência, início/fim, passagem rápida, histerese,
posições duplicadas ou fora de ordem, reinicialização, ações manuais,
idempotência, reconciliação de condutor, múltiplas rotas e a ausência de comandos
de encerramento no cliente Trafegus.

## Monitoramento da rota operacional

A rota ativa `betim-jaboatao` é versionada no SQLite e gerada pelo TomTom Routing no perfil caminhão, passando pelos cinco pontos operacionais obrigatórios. A versão `tomtom-mandatory-v1` mantém a geometria integral para detectar desvios; a API simplifica somente a cópia enviada ao mapa.

- A rota planejada aparece tracejada e atrás dos veículos e alertas.
- O percurso realizado usa posições persistidas e separa segmentos com saltos incompatíveis.
- O corredor padrão é 300 m; o desvio exige duas leituras externas consecutivas.
- Os níveis são inicial, moderado após 30 minutos e máximo após 60 minutos.
- O retorno exige duas leituras internas consecutivas; posições antigas não alteram o estado.
- A cerca da origem permanece em 500 m. A do destino usa entrada de 1.000 m e saída de 1.150 m, lidas da configuração da rota.

Endpoints: `GET /routes/{id}/geometry`, `GET /routes/{id}/paths`, `GET /deviations/active`, `GET /deviations/trips/{trip_key}`, `POST /deviations/{id}/acknowledge` e `POST /deviations/{id}/close`. A correção ou remoção real de um vínculo exige confirmação e justificativa em `POST /operations/trips/{trip_key}/driver-association`. O X da Visão Geral apenas oculta na interface e nunca chama esse endpoint.

As preferências de motorista oculto e fixado ficam somente no `localStorage`. Os cards filtram mapa e lista sem modificar os contadores completos ou dados operacionais.

### Avaliação futura de Planejar rota

A tela continua separada da Visão Geral e simulações não substituem a rota operacional. Uma reformulação futura pode organizar paradas em uma linha do tempo, comparar versões de geometria e exigir uma revisão explícita antes da ativação.

## Velocidade e progresso da viagem

A “Situação da Frota” reutiliza a velocidade e o timestamp do snapshot compartilhado do Trafegus; nenhum indicador cria chamadas adicionais. `FLEET_POSITION_FRESH_MINUTES` define quando velocidade e posição passam a ser apresentadas como desatualizadas.

A quilometragem é calculada pela projeção da posição sobre a geometria oficial versionada. O sistema persiste distância total, avanço, restante, percentual, confiabilidade e última estimativa confiável em `route_progress_snapshots`. Pequenas oscilações não reduzem o progresso. Quando o veículo está fora do corredor, o restante oficial e a aproximação de retorno à rota são mostrados separadamente.

Confiabilidade: alta para posição recente e coerente na rota, média para posição recente fora do corredor, baixa para posição antiga preservada e indisponível quando faltam geometria ou posição. O Trafegus continua estritamente somente leitura: uma autenticação, uma consulta de posições e duas consultas de detalhe por veículo em cada ciclo compartilhado, no intervalo configurado por `FLEET_COLLECTOR_INTERVAL_SECONDS`.

### Limitação da velocidade no endpoint coletivo

O endpoint coletivo `ultima-posicao-viagem` atualmente retorna a posição da viagem, mas não inclui velocidade ou telemetria no objeto `viagem[].posicoesViagem`. A interface mostra `Sem velocidade` nessa situação. O parser preserva corretamente valores numéricos ou textuais, inclusive `0`, caso o provedor passe a incluir o campo. O endpoint individual `ultimaPosicaoVeiculo` não é usado na frota para evitar uma chamada adicional por motorista.
# Base AngelLira

A versão operacional fica em `data/angellira/2026-07-23-v1`. A importação
valida manifesto, versão, schema, contagens e checksums antes de escrever no
SQLite. Repetir a mesma importação é seguro e gera apenas um evento auditável
de `IMPORT_NOOP`.

```powershell
.\.venv-run\Scripts\python.exe -m scripts.angellira_data import --actor operador
.\.venv-run\Scripts\python.exe -m scripts.angellira_data status
```

A geocodificação é uma tarefa offline explícita, usa o TomTom configurado e
reaproveita o cache. Somente os 180 registros preparados entram na fila;
resultados incertos e todos os registros marcados para revisão manual continuam
pendentes. Um resultado só aparece no mapa quando o status final é `validated`.

```powershell
.\.venv-run\Scripts\python.exe -m scripts.angellira_data geocode --limit 25 --actor operador
```

Endpoints públicos são somente leitura: `GET /angellira/status`,
`GET /angellira/stations`, `GET /angellira/risk-areas` e
`GET /angellira/admin`. A camada de postos fica desligada por padrão e é apenas
visual; postos nunca geram alerta.

As 28 áreas estimadas atuais não têm geometria, não aparecem no mapa e não
participam de alertas. O motor futuro de permanência aceita somente geometria
WGS84 `Polygon` ou `MultiPolygon` validada e versionada. Ele exige viagem ativa,
posição recente, três leituras internas, pelo menos 15 minutos e movimento de
parada; respeita as prioridades de cerca oficial, posto validado e corredor.
Após 30 minutos, um alerta só se torna crítico quando existe um segundo fator
confiável.

Se uma nova versão falhar na importação, não edite o banco manualmente:
confira primeiro o caminho, o manifesto e os checksums. Corrija a origem do
pacote e repita o comando; a transação é revertida integralmente em caso de
erro.
