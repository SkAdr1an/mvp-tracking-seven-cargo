# 🎯 Fluxo Completo: Rastreamento + Trafegus

## FLUXO 1: Motorista enviando localização (SEM POLLING)

```
┌─────────────────────────────────────────────────────────────────┐
│                    APP DO MOTORISTA (Mobile)                     │
│                                                                   │
│  navigator.geolocation.watchPosition(position => {              │
│      ws.send({                                                   │
│          latitude, longitude, speed, heading, battery            │
│      })                                                           │
│  })                                                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket: ws://server/tracking/ws/driver/123
                           │ (Conexão persistente - NÃO POLLING!)
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│              SERVIDOR FASTAPI (Tracking)                         │
│                                                                   │
│  @websocket("/ws/driver/{driver_id}")                           │
│  async def websocket_driver(ws, driver_id):                     │
│      while True:                                                 │
│          data = await ws.receive_json()  # Aguarda updates      │
│          active_drivers[driver_id] = data                        │
│          await broadcast_to_managers(data)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Broadcast em tempo real
                           ↓
┌──────────────────────────────────────────────────────────────────┐
│              DASHBOARD DO GERENTE (Browser)                      │
│                                                                   │
│  ws://server/tracking/ws/manager                                │
│                                                                   │
│  ws.onmessage = (event) => {                                    │
│      const {driver_id, location} = JSON.parse(event.data)       │
│      map.updateMarker(driver_id, location)  // Atualiza mapa    │
│      sidebar.update(driver_id, location)    // Atualiza lista    │
│  }                                                               │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 🗺️  MAPA COM MOTORISTAS EM TEMPO REAL                   │   │
│  │                                                           │   │
│  │    🟢 motorista_001 (65.4 km/h)                         │   │
│  │    🟢 motorista_002 (45.2 km/h)                         │   │
│  │    🟡 motorista_003 (parado)                            │   │
│  │    🔴 motorista_004 (offline)                           │   │
│  │                                                           │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## FLUXO 2: Integração com Trafegus (Incidentes de Tráfego)

```
┌─────────────────────────────────────────────────────┐
│          ROTA PLANEJADA (Betim → Jaboatão)         │
│                                                      │
│  POST /routes/preview                               │
│  {                                                   │
│    origin: "Betim, MG",                            │
│    destination: "Jaboatão, PE",                    │
│    departure_at: "2026-07-20T12:00:00"             │
│  }                                                   │
└──────────────────────┬───────────────────────────────┘
                       │
                       ↓
┌──────────────────────────────────────────────────────┐
│        SERVIDOR: Calcular rota (TomTom)             │
│                                                       │
│  route = await TomTomClient.get_route(...)          │
│  coords = [                                          │
│      (lat_origem, lon_origem),                       │
│      ... waypoints intermediários ...,              │
│      (lat_destino, lon_destino)                     │
│  ]                                                   │
└──────────────────────┬───────────────────────────────┘
                       │
                       ↓
┌──────────────────────────────────────────────────────────┐
│    SERVIDOR: Verificar incidentes ao longo da rota      │
│    (Trafegus API)                                        │
│                                                           │
│    for each waypoint in route:                          │
│        incidents = await TrafegusClient               │
│            .get_incidents_by_coordinates(              │
│                lat, lon, radius=50km                   │
│            )                                            │
│        if incidents:                                    │
│            route_incidents.append(incidents)           │
│                                                           │
│    Exemplo resposta Trafegus:                          │
│    {                                                    │
│      "incidents": [                                     │
│        {                                                │
│          "type": "accident",                           │
│          "severity": "high",                           │
│          "location": "BR-381 Km 45",                   │
│          "description": "Colisão múltipla",           │
│          "timestamp": "2026-07-20T14:30:00"           │
│        },                                              │
│        {                                                │
│          "type": "roadwork",                           │
│          "severity": "medium",                         │
│          "location": "BR-101 Km 200"                   │
│        }                                                │
│      ]                                                 │
│    }                                                    │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ↓
┌────────────────────────────────────────────────────────────┐
│  RESPOSTA DO MVP: Rota com incidentes                      │
│                                                             │
│  {                                                          │
│    "origin": {...},                                        │
│    "destination": {...},                                   │
│    "distance_km": 2092.08,                                │
│    "duration_with_traffic_minutes": 1918.6,              │
│    "status": "normal",                                     │
│    "incidents": [                  👈 NOVO!              │
│      {                                                      │
│        "type": "accident",                                 │
│        "severity": "high",                                 │
│        "location": "BR-381 Km 45",                         │
│        "when": "14h30",                                    │
│        "recommendation": "Desviar por BR-116"            │
│      }                                                      │
│    ]                                                       │
│  }                                                         │
└────────────────────────────────────────────────────────────┘
```

---

## FLUXO 3: Dashboard com Rastreamento + Incidentes

```
┌──────────────────────────────────────────────────────────────┐
│           DASHBOARD DO GERENTE (Tempo Real)                  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 📊 STATUS                                              │ │
│  │ ✅ Conectado ao WebSocket | 3 motoristas online       │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 🗺️  MAPA (Leaflet)                                     │ │
│  │                                                         │ │
│  │   [Mapa com motoristas em tempo real]                 │ │
│  │   🟢 motorista_001: Betim (-19.96, -44.19)            │ │
│  │       Velocidade: 65.4 km/h                           │ │
│  │       Status: EM ROTA                                 │ │
│  │       ETA: Amanhã 20h00                               │ │
│  │                                                         │ │
│  │   🟡 motorista_002: Estrada (em movimento)            │ │
│  │       Velocidade: 0 km/h (PARADO!)                    │ │
│  │       Bateria: 45%                                    │ │
│  │       ⚠️  ALERTA: Saída de rota detectada!           │ │
│  │                                                         │ │
│  │   🔴 motorista_003: OFFLINE                           │ │
│  │       Última localização: 2h atrás                     │ │
│  │                                                         │ │
│  │   ⛔️ INCIDENTES DETECTADOS:                           │ │
│  │   • Acidente em BR-381 Km 45 (ALTO)                   │ │
│  │   • Obras em BR-101 Km 200 (MÉDIO)                    │ │
│  │   • Congestionamento em Recife (BAIXO)                │ │
│  │                                                         │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 📋 LISTA DE MOTORISTAS (Sidebar)                       │ │
│  │                                                         │ │
│  │ 🟢 motorista_001                                       │ │
│  │    Localização: Betim, MG                             │ │
│  │    Velocidade: 65.4 km/h                              │ │
│  │    Bateria: 92% | Sinal: -45 dBm                      │ │
│  │    Atualizado: 2s atrás                               │ │
│  │                                                         │ │
│  │ 🟡 motorista_002                                       │ │
│  │    Localização: Estrada BR-381                        │ │
│  │    Velocidade: 0 km/h ⚠️                              │ │
│  │    Bateria: 45% | Sinal: -65 dBm                      │ │
│  │    Status: PARADO há 12 minutos                       │ │
│  │    [Clicar para abrir rota]                           │ │
│  │                                                         │ │
│  │ 🔴 motorista_003                                       │ │
│  │    Última localização: Recife                         │ │
│  │    Última atualização: 2h10min atrás                  │ │
│  │    Status: OFFLINE                                     │ │
│  │                                                         │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## FLUXO 4: Arquitetura em Produção (Escalável)

```
┌────────────────────────────────────────────────────────────┐
│                    MÚLTIPLOS MOTORISTAS                     │
│                                                             │
│  🚗 Driver_001 ──┐                                          │
│  🚗 Driver_002 ──┼─→ WebSocket Server 1                    │
│  🚗 Driver_003 ──┘                                          │
│                                                             │
│  🚗 Driver_004 ──┐                                          │
│  🚗 Driver_005 ──┼─→ WebSocket Server 2                    │
│  🚗 Driver_006 ──┘                                          │
└────────────────────┬─────────────────────────────────────┘
                     │ Publicar em Redis
                     ↓
┌────────────────────────────────────────────────────────────┐
│              REDIS (PubSub / Streams)                       │
│                                                             │
│  SUBSCRIBE driver:*                                         │
│  ├─ Todos os servers subscrevem                            │
│  ├─ Qualquer update é replicado                            │
│  └─ Histórico preservado em Streams                        │
└────────────────────┬─────────────────────────────────────┘
                     │ Distribuir
                     ↓
┌──────────────────────────────────────────────────────────────┐
│                MÚLTIPLOS DASHBOARDS                          │
│                                                              │
│  👨‍💼 Gerente 1 ──→ WebSocket Client → Recebe updates      │
│  👨‍💼 Gerente 2 ──→ WebSocket Client → Recebe updates      │
│  👨‍💼 Gerente 3 ──→ WebSocket Client → Recebe updates      │
│                                                              │
│  Todos veem a mesma informação em TEMPO REAL!              │
└──────────────────────────────────────────────────────────────┘
```

---

## 📊 Comparação: Polling vs WebSocket

### HTTP Polling (❌ Antigo)
```
Cliente                              Servidor
  │                                    │
  ├─ GET /driver/123/location ───────→│
  │                                    │
  │←─────────── 200 + JSON ────────────┤
  │                                    │
  │ [Aguarda 5 segundos]               │
  │                                    │
  ├─ GET /driver/123/location ───────→│
  │                                    │
  │←─────────── 200 + JSON ────────────┤
  │                                    │
  │ [Aguarda 5 segundos]               │
  │                                    │
  └─ GET /driver/123/location ───────→│
     (E assim vai... por HORAS! 🔋)
```

**Problemas:**
- ❌ 43.200 requisições por dia por motorista!
- ❌ Latência de 2.5 segundos (metade do intervalo)
- ❌ Drena bateria do device
- ❌ Consome muita banda

---

### WebSocket (✅ Novo)

```
Cliente                              Servidor
  │                                    │
  ├─ CONNECT ─────────────────────────→│
  │←─ 101 Upgrade ─────────────────────┤
  │                                    │
  │ [Conexão aberta permanentemente]   │
  │                                    │
  │ [Motorista se move]                │
  │                                    │
  │ ├─ {lat: -8.11, lon: -35.01} ────→│
  │                                    │
  │←─ ACK ─────────────────────────────┤
  │                                    │
  │ [Motorista não se move]            │
  │ (Sem envio = sem consumo! ⚡)     │
  │                                    │
  │ [Motorista se move novamente]      │
  │                                    │
  │ ├─ {lat: -8.12, lon: -35.02} ────→│
  │                                    │
  │←─ ACK ─────────────────────────────┤
```

**Benefícios:**
- ✅ Apenas ~300 requisições por dia (só quando se move!)
- ✅ Latência <100ms
- ✅ Eficiente em bateria
- ✅ Banda mínima

---

## 🎯 Resumo da Implementação

| Feature | Status | Details |
|---------|--------|---------|
| **WebSocket Driver** | ✅ Implementado | `/ws/driver/{id}` - Motorista envia localização |
| **WebSocket Manager** | ✅ Implementado | `/ws/manager` - Gerente recebe atualizações |
| **Fallback HTTP** | ✅ Implementado | GET/POST endpoints para fallback |
| **Trafegus API** | ✅ Pronto | Integração completa, falta API key |
| **Dashboard HTML** | ✅ Implementado | Mapa em tempo real com Leaflet |
| **Cliente Python** | ✅ Implementado | Simulador de rota para testes |
| **React Native** | ✅ Documentado | Pronto para implementar em app |
| **Flutter** | ✅ Documentado | Pronto para implementar em app |

---

## 🚀 Próximos Passos

1. **Forneça a API Key do Trafegus** → Eu integro totalmente
2. **Deploy em produção** → Adicionar Redis para múltiplos servidores
3. **App móvel** → React Native ou Flutter
4. **Análises** → Usar ClickHouse para dados históricos
5. **Alertas** → Notificações de desvio, excesso de velocidade, etc
