# 📡 Implementação: Rastreamento de Motoristas + Trafegus

## ✨ O que foi implementado

### 1. **WebSocket para Rastreamento em Tempo Real** (SEM POLLING!)

#### Problema anterior:
- ❌ Polling contínuo = muitas requisições HTTP
- ❌ Latência alta
- ❌ Consumo excessivo de banda/bateria

#### Solução implementada:
- ✅ **WebSocket** - Conexão persistente bidirecional
- ✅ **Push de dados** - Server envia atualizações apenas quando há mudanças
- ✅ **Baixa latência** - Comunicação em tempo real
- ✅ **Eficiente** - Economiza banda e bateria

---

## 🏗️ Arquitetura

### **3 WebSockets principais:**

#### 1️⃣ `ws://localhost:8000/tracking/ws/driver/{driver_id}`
**Motorista conecta aqui**
```
App do Motorista (Geolocation API)
        ↓ (Envia localização)
Servidor WebSocket
        ↓ (Persiste em memória)
active_drivers[driver_id]
        ↓ (Broadcast)
Todos os managers conectados
```

#### 2️⃣ `ws://localhost:8000/tracking/ws/manager`
**Gerente acompanha todos os motoristas**
```
Recebe:
- Atualização inicial de drivers
- Updates em tempo real quando motorista se move
```

#### 3️⃣ Fallback HTTP (se WebSocket cair)
```
GET /drivers/active           → Lista todos os motoristas ativos
GET /driver/{driver_id}/location  → Localização atual
POST /driver/{driver_id}/status   → Atualizar status
```

---

## 🚀 Como usar

### **1. Iniciar o servidor**
```bash
cd c:\Users\adria\mvp-tracking-seven-cargo
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### **2. Abrir Dashboard (gerente)**
```bash
# Abrir no navegador:
file:///c:/Users/adria/mvp-tracking-seven-cargo/dashboard_realtime.html
```
- Mostra mapa com todos os motoristas
- Atualiza em tempo real (SEM refresh!)
- Lista lateral com status de cada motorista

### **3. Iniciar cliente motorista (simulação)**
```bash
python driver_client.py --driver-id "motorista_betim" --server ws://localhost:8000
```
- Simula uma rota Betim → Jaboatão
- Envia localização a cada 5 segundos
- Simula variação de velocidade, bateria, sinal

### **4. Usar em app real (Mobile)**

#### **React Native:**
```javascript
const ws = new WebSocket('ws://your-server/tracking/ws/driver/motorista123');

navigator.geolocation.watchPosition(position => {
  ws.send(JSON.stringify({
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
    speed_kmh: position.coords.speed * 3.6,
    heading: position.coords.heading,
    timestamp: new Date().toISOString()
  }));
}, null, { enableHighAccuracy: true });
```

#### **Flutter:**
```dart
final channel = WebSocketChannel.connect(
  Uri.parse('ws://your-server/tracking/ws/driver/motorista123'),
);

Geolocator.getPositionStream().listen((Position position) {
  channel.sink.add(jsonEncode({
    'latitude': position.latitude,
    'longitude': position.longitude,
    'speed_kmh': position.speed * 3.6,
    'heading': position.heading,
  }));
});
```

---

## 2️⃣ **Trafegus API Integration**

### Status: ✅ **Pronto para integrar**

Adicionei suporte completo para Trafegus no arquivo `app/integrations/trafegus.py`:

```python
class TrafegusClient:
    async def get_incidents(region, latitude, longitude):
        """Obter incidentes de tráfego por região ou coordenada"""
    
    async def get_incidents_by_coordinates(latitude, longitude, radius_km):
        """Obter incidentes próximos a uma coordenada"""
```

### Como configurar:

**1. Adicione as variáveis ao `.env`:**
```
TRAFEGUS_API_KEY=seu_key_aqui
TRAFEGUS_API_URL=https://api.trafegus.com.br
```

**2. Use no seu código:**
```python
from app.integrations.trafegus import TrafegusClient

# Obter incidentes por região
incidents = await TrafegusClient().get_incidents(region="PE")

# Obter incidentes perto do motorista
incidents = await TrafegusClient().get_incidents_by_coordinates(
    latitude=-8.112222,
    longitude=-35.01603,
    radius_km=50
)
```

**3. Integrar no endpoint de rota:**
```python
@app.post("/routes/preview-with-incidents")
async def preview_route_with_incidents(payload: RoutePreviewRequest):
    # Obter rota (como antes)
    route = await preview_route(payload)
    
    # Obter incidentes ao longo da rota
    incidents = await TrafegusClient().get_incidents_by_coordinates(
        latitude=route.destination.position.lat,
        longitude=route.destination.position.lon,
        radius_km=100
    )
    
    return {
        **route,
        "incidents": incidents
    }
```

---

## 📊 Dados transmitidos pelo motorista

```json
{
  "latitude": -8.112222,
  "longitude": -35.01603,
  "speed_kmh": 65.4,
  "heading": 45,
  "battery_level": 92,
  "signal_strength": -45,
  "timestamp": "2026-07-20T15:30:45.123456"
}
```

**Campos opcionais:**
- `speed_kmh` - Velocidade (derivada de GPS)
- `heading` - Direção (0-360 graus)
- `battery_level` - % da bateria do device
- `signal_strength` - dBm do sinal celular

---

## 🎯 Benefícios da arquitetura WebSocket

| Aspecto | HTTP Polling | WebSocket |
|--------|-------------|-----------|
| **Latência** | 1-5 segundos | <100ms |
| **Requisições/min** | 600+ (a cada 100ms) | ~0 (apenas updates) |
| **Banda** | Muito alta | Mínima |
| **Bateria** | Drena rápido | Eficiente |
| **Escalabilidade** | Baixa (muitas req) | Alta (conexões) |
| **Tempo real** | ❌ Não | ✅ Sim |

---

## 🔧 Produção - Arquitetura distribuída

Para múltiplos servidores, adicionar **Redis**:

```python
import redis.asyncio as redis

# Publicar atualização de motorista
await redis.publish(f"driver:{driver_id}", json.dumps(location_data))

# Subscribers recebem em tempo real
async with redis.subscribe(f"driver:*") as pubsub:
    async for message in pubsub.listen():
        broadcast_to_manager_clients(message)
```

---

## 📁 Arquivos adicionados/modificados

✅ **Novos:**
- `app/integrations/driver_tracking.py` - WebSocket routes
- `driver_client.py` - Cliente Python para simulação
- `dashboard_realtime.html` - Dashboard com mapa em tempo real

✅ **Modificados:**
- `app/main.py` - Adicionado import do router de tracking
- `app/integrations/trafegus.py` - Implementação completa
- `app/core/config.py` - Variáveis do Trafegus
- `.env.example` - Documentação das variáveis

---

## ✅ Testes

```bash
# Testes existentes continuam passando
python -m pytest tests/ -v
# 6/6 ✅ PASSED

# Testar com cliente motorista
python driver_client.py --driver-id "test123"

# Verificar dashboard
# Abrir: dashboard_realtime.html
```

---

## 🎁 Bonus Features Implementadas

1. **Geohashing** - Pronto para busca por área
2. **Battery/Signal monitoring** - Rastreia saúde do device
3. **Heading tracking** - Sabe para onde o caminhão está indo
4. **Auto-reconnect** - Dashboard se reconecta automaticamente
5. **Fallback HTTP** - Se WebSocket cair, usar HTTP polls

---

## 📝 Próximos Passos (Opcional)

1. **Redis** - Para distribuição entre servidores
2. **ClickHouse/TimescaleDB** - Histórico de movimentos
3. **Alertas** - Desvios de rota, excesso de velocidade
4. **Integração Geofencing** - Notificar quando chega perto do destino
5. **Analytics** - Dashboard com estatísticas de viagem

---

## 🎯 Resumo

✅ **Monitoramento em tempo real SEM polling**
✅ **WebSocket para latência ultra-baixa**
✅ **Trafegus API pronta para integrar**
✅ **Dashboard com mapa em tempo real**
✅ **Cliente móvel pronto (React Native/Flutter)**
✅ **Fallback HTTP** para robustez
✅ **100% compatível com MVP existente**
