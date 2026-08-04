# Homologação controlada — Portal do Motorista

## Ativação segura

Os dois recursos permanecem desligados por padrão. Uma viagem só participa quando
as flags globais e a lista explícita estiverem configuradas:

```env
DRIVER_MOBILE_LOCATION_ENABLED=true
DRIVER_PORTAL_ALERTS_ENABLED=true
DRIVER_PORTAL_PILOT_TRIP_KEYS=chave-da-viagem-selecionada
```

Uma lista vazia não habilita nenhuma viagem. Para desligar imediatamente, defina as
duas flags como `false` ou remova a chave da lista. Não use `*`. A seleção é validada
no backend; o frontend não informa nem escolhe a identidade da viagem.

## Checklist do teste real

- Identificação interna do teste (sem token ou coordenadas no relatório)
- Modelo do celular
- Android ou iPhone e versão
- Navegador e versão
- Permissão de localização concedida/recusada
- Frequência real de atualização
- Consumo percebido de bateria
- Comportamento com tela ligada
- Comportamento com tela bloqueada
- Comportamento com navegador minimizado
- Perda e recuperação da internet
- Utilidade, atraso, incorreção e repetição dos alertas
- Distância percebida como suficiente
- Facilidade de uso e legibilidade
- Funcionamento do WhatsApp Central

O navegador pode reduzir ou suspender a geolocalização com a tela bloqueada, o
navegador minimizado ou o modo de economia de bateria. Isso varia especialmente
entre Safari/iPhone e navegadores Android. O portal precisa permanecer aberto e não
há garantia de rastreamento contínuo em segundo plano.

## Roteiro Android e iPhone

Em cada plataforma, testar em Wi-Fi e rede móvel: consentir, recusar e reativar a
permissão; manter a tela ligada por 15 minutos; bloquear por 10 minutos; minimizar;
alternar modo avião; recuperar a conexão; conferir idade e fonte; validar alertas e
WhatsApp. Registrar observações, sem inserir fixtures ou simulações no banco real.

## Simulações e métricas

As simulações ficam em `tests/fixtures` e usam bancos temporários/mocks. O comando
abaixo resume um arquivo exportado separado, sem abrir `data/operations.db`:

```powershell
python -m scripts.report_driver_portal_homologation tests/fixtures/driver_portal_homologation.json
```

Os indicadores são: posições aceitas, idade média do celular, disponibilidade do
Trafegus, tempo como fonte complementar, alertas apresentados, repetições bloqueadas,
descartes por posição atrás ou idade, divergências e falhas por plataforma/navegador.

## Resultado desta etapa

- Matriz automatizada com os 32 cenários obrigatórios: preparada e rastreada.
- Simulações: fixtures e mocks isolados; nenhum dado operacional foi usado.
- Testes físicos Android/iPhone: pendentes de piloto autorizado com aparelhos reais.
- Distâncias: mantidas como hipóteses; nenhuma alteração automática foi feita.
- Recomendação: iniciar com uma única viagem selecionada, observar um ciclo completo,
  revisar falsos positivos e bateria e só então propor ajustes documentados.

Não foram adicionados push, PWA, service worker, postos homologados ou ativação geral.
