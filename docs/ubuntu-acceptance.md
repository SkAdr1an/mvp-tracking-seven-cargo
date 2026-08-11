# Portão obrigatório de homologação em Ubuntu

Este roteiro deve ser executado em uma VPS Ubuntu limpa antes da homologação
online. Ele não foi executado na estação Windows de desenvolvimento.

## Preparação

1. Instalar Docker Engine e o plugin Docker Compose suportados pelo Ubuntu.
2. Fazer checkout do hash candidato e criar o `.env` fora do Git, a partir do
   `.env.example`, usando segredos novos e domínio HTTPS real.
3. Confirmar que nenhum banco ou volume anterior existe para o nome do projeto.
4. Executar `docker compose config` e revisar somente nomes/presença das
   variáveis; nunca imprimir os valores secretos.

## Volume novo, build e migração

1. Executar `docker compose build --pull`.
2. Executar `docker compose up volume-init` e exigir saída zero.
3. Inspecionar o volume por um container efêmero e confirmar UID/GID `10001`,
   diretórios com modo `0750` e ausência de permissões `777`.
4. Executar `docker compose run --rm migrate` duas vezes. Ambas devem terminar
   com sucesso e a segunda não pode alterar hash lógico, dados ou `updated_at`.
5. Executar `PRAGMA integrity_check`, `PRAGMA foreign_key_check` e conferir a
   versão em `schema_migrations`.
6. Simular falha numa cópia descartável e confirmar rollback integral. Nunca
   realizar essa simulação no volume candidato.

## Inicialização e persistência

1. Executar `docker compose up -d` e aguardar todos os healthchecks.
2. Confirmar que o backend executa como UID `10001`, não possui porta publicada
   no host e não altera schema ao iniciar.
3. Criar somente um registro sintético autorizado, reiniciar os containers e
   confirmar persistência.
4. Confirmar login, logout e impossibilidade de reutilizar o cookie capturado.
5. Desativar o usuário sintético no arquivo externo e confirmar `401` imediato.

## Proxy, PDF e WebSocket

1. Validar redirecionamento HTTP para HTTPS e certificado completo.
2. Baixar um relatório pelo frontend; exigir `application/pdf`, nome `.pdf`,
   assinatura `%PDF-`, abertura normal e ausência de caminhos internos.
3. Validar WebSocket autenticado através do Nginx e rejeição sem credencial.
4. Inspecionar logs para garantir que cookies, tokens e query strings sensíveis
   não foram registrados.

## Backup, restauração e rollback

1. Produzir backup consistente pela API de backup do SQLite com os serviços de
   escrita controlados.
2. Copiar o backup criptografado para armazenamento externo à VPS.
3. Restaurar em volume novo, executar os dois PRAGMAs e comparar contagens e
   amostras sintéticas.
4. Testar rollback da aplicação para o hash anterior usando uma cópia do volume.
5. Para rollback de schema, restaurar o backup anterior à migração; não aplicar
   scripts destrutivos diretamente no único volume disponível.
6. Registrar duração, responsáveis, RPO/RTO observados e evidências dos testes.
