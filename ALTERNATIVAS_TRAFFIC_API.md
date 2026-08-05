# 🚨 Alternativas de APIs de Tráfego para Trafegus

## 1️⃣ **TomTom Traffic API** (Que você JÁ usa! 🎉)

**Melhor opção:** Você já tem a chave do TomTom!

```python
# TomTom já inclui dados de tráfico nas respostas
# Você pode aproveitar os dados que já recebe!

class TomTomTrafficIntegration:
    async def get_traffic_info(self, route_response):
        """
        TomTom já retorna:
        - trafficDelayInSeconds
        - travelTimeInSeconds  
        - trafficLengthInMeters
        
        Você pode extrair alertas diretamente!
        """
        route = route_response['routes'][0]
        summary = route['summary']
        
        traffic_delay = summary['trafficDelayInSeconds']
        
        # Classificar severidade
        if traffic_delay > 3600:  # > 1 hora
            return {"severity": "critical", "delay": traffic_delay}
        elif traffic_delay > 1800:  # > 30 min
            return {"severity": "high", "delay": traffic_delay}
        elif traffic_delay > 600:  # > 10 min
            return {"severity": "medium", "delay": traffic_delay}
        else:
            return {"severity": "low", "delay": traffic_delay}
```

**Vantagem:** Você já paga pela chave, está incluído!

---

## 2️⃣ **OpenWeatherMap Traffic** (Gratuito!)

**Plano gratuito disponível**
- API Key: Você já tem (openweather_api_key)
- Dados de tráfego por coordenadas

```python
class OpenWeatherTraffic:
    """
    Usar a mesma chave do OpenWeather que você já tem!
    """
    
    async def get_traffic_flow(self, latitude: float, longitude: float):
        """
        GET https://api.openweathermap.org/v3/stations
        Retorna flow de tráfego por coordenada
        """
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.openweathermap.org/v3/stations",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "appid": self.api_key
                }
            )
            
            return response.json()
```

**Vantagem:** Usa a mesma chave que você já tem!

---

## 3️⃣ **HERE Maps API** (Excelente para Brasil)

**Gratuito até 250k requisições/mês**

```python
class HEREMapsTraffic:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://traffic.ls.hereapi.com/traffic/6.3"
    
    async def get_flow(self, latitude: float, longitude: float, radius: int = 1000):
        """
        Obter fluxo de tráfego ao redor de coordenada
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/flow.json",
                params={
                    "apiKey": self.api_key,
                    "bbox": f"{latitude-0.1},{longitude-0.1},{latitude+0.1},{longitude+0.1}",
                    "responseAttributes": "sh,fc"
                }
            )
            return response.json()
    
    async def get_incidents(self, latitude: float, longitude: float):
        """
        Obter incidentes (acidentes, obras, etc)
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/incidents.json",
                params={
                    "apiKey": self.api_key,
                    "bbox": f"{latitude-0.2},{longitude-0.2},{latitude+0.2},{longitude+0.2}",
                    "responseAttributes": "sh,fc,c,t"
                }
            )
            return response.json()
```

**Plano gratuito:** 250k requisições/mês (suficiente para MVP!)
**Vantagem:** Excelente para Brasil!

---

## 4️⃣ **Mapbox Traffic** (Very good)

**Gratuito com limite**
- 50k requisições/mês no plano free

```python
class MapboxTraffic:
    def __init__(self, access_token: str):
        self.token = access_token
        self.base_url = "https://api.mapbox.com/traffic/v1"
    
    async def get_traffic_data(self, longitude: float, latitude: float, z: int = 12):
        """
        Obter tiles de tráfego
        """
        url = f"{self.base_url}/traffic/v1/{z}/{x}/{y}.png"
        
        params = {"access_token": self.token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            return response.content
```

**Vantagem:** Integra bem com Leaflet (que você já usa!)

---

## 5️⃣ **Google Maps Platform** (Poderoso mas caro)

**Não recomendado para MVP** (pagas por requisição)
```python
# Não implementar agora - muito caro
```

---

## 6️⃣ **Dados Abertos Brasil** (Gratuito! 🇧🇷)

**DENATRAN + DNIT** (Governo)
```python
class BrasilTrafficOpen:
    """
    Dados públicos de tráfego brasileiro
    Pode conter dados de rodovias federais
    """
    
    async def get_federal_road_conditions(self):
        """
        DNIT publica dados de rodovias federais
        https://www.gov.br/infraestrutura/pt-br/assuntos/transito
        """
        # Verificar datasets disponíveis em:
        # https://dados.gov.br/
        pass
```

---

## 7️⃣ **Waze API** (Não oficial)

**⚠️ Não recomendado** - Sem API oficial pública
- Existe scraping não autorizado
- Pode violar ToS

---

## 🎯 **MINHA RECOMENDAÇÃO PARA VOCÊ**

### **Opção 1: Usar TomTom que você já tem! ✅ (MELHOR)**

```python
# Você JÁ paga por TomTom, então aproveita!

@app.post("/routes/preview-with-traffic")
async def preview_route_with_traffic(payload: RoutePreviewRequest):
    # Calcular rota (como faz agora)
    route = await TomTomClient().get_route(...)
    summary = route['routes'][0]['summary']
    
    # Extrair dados de tráfego que TomTom já inclui!
    traffic_delay = summary['trafficDelayInSeconds']
    traffic_length = summary.get('trafficLengthInMeters', 0)
    
    # Classificar severidade
    severity = classify_traffic_severity(traffic_delay)
    
    return {
        **route_response,
        "traffic": {
            "delay_seconds": traffic_delay,
            "delay_minutes": traffic_delay / 60,
            "affected_distance_km": traffic_length / 1000,
            "severity": severity,  # low, medium, high, critical
            "recommendation": get_recommendation(severity)
        }
    }
```

**Vantagem:** Você já paga! Aproveita dados que já recebe!

---

### **Opção 2: Adicionar HERE Maps (Gratuito até 250k/mês)**

**Passo 1:** Registrar em https://developer.here.com/
- Gratuito
- Instant API Key

**Passo 2:** Adicionar ao .env
```
HERE_API_KEY=seu_key_aqui
```

**Passo 3:** Implementar
```python
from app.integrations.here_maps import HERETraffic

@app.post("/routes/preview-with-incidents")
async def preview_route_with_incidents(payload: RoutePreviewRequest):
    route = await TomTomClient().get_route(...)
    
    # Pegar incidentes do HERE
    incidents = await HERETraffic().get_incidents(
        latitude=dest_lat,
        longitude=dest_lon
    )
    
    return {
        **route_response,
        "incidents": incidents
    }
```

**Vantagem:** 
- 250k requisições/mês (mais que suficiente!)
- Excelente para Brasil
- Gratuito
- Complementa TomTom

---

### **Opção 3: Combinar TomTom + HERE (O IDEAL 🚀)**

```python
@app.post("/routes/preview-complete")
async def preview_route_complete(payload: RoutePreviewRequest):
    # 1. Rota com tráfego (TomTom)
    route = await TomTomClient().get_route(...)
    
    # 2. Incidentes (HERE)
    incidents = await HERETraffic().get_incidents(...)
    
    # 3. Clima (OpenWeather)
    weather = await WeatherClient().get_current_weather_by_coords(...)
    
    return {
        "route": route,
        "traffic": {
            "delay": route_summary['trafficDelayInSeconds'],
            "severity": classify_traffic(...)
        },
        "incidents": incidents,
        "weather": weather,
        "recommendations": generate_recommendations(...)
    }
```

---

## 📊 Comparação de Opções

| API | Custo | Brasil | Incidentes | Delay | Recomendação |
|-----|-------|--------|-----------|-------|--------------|
| **TomTom** (você tem) | ✅ Já paga | ✅ Excelente | ⚠️ Básico | ✅ Sim | **✅ USE AGORA** |
| **HERE Maps** | ✅ Grátis 250k | ✅ Ótimo | ✅ Sim | ⚠️ Não | **✅ ADICIONE AGORA** |
| **OpenWeather** | ✅ Já tem | ⚠️ OK | ❌ Não | ❌ Não | Apenas clima |
| **Mapbox** | ⚠️ 50k/mês | ✅ OK | ✅ Sim | ❌ Não | Backup |
| **Google** | ❌ Caro | ✅ OK | ✅ Sim | ✅ Sim | Não para MVP |
| **Waze** | ⚠️ Não oficial | ✅ OK | ✅ Sim | ✅ Sim | Não recomenda |

---

## 🚀 Plano de Ação Recomendado

### **Fase 1 (AGORA):** Usar TomTom que você já tem
```python
# Já implementado no código! Basta extrair melhor os dados
await TomTomClient().get_route(...) 
# Inclui trafficDelayInSeconds
```

### **Fase 2 (HOJE):** Registrar e adicionar HERE Maps
```
1. Ir para https://developer.here.com
2. Criar conta (5 min)
3. Copiar API Key
4. Adicionar ao .env: HERE_API_KEY=...
5. Implementar HERETraffic no MVP
```

### **Fase 3 (FUTURO):** Integrar com Trafegus quando tiver chave
```python
# Adicionar como terceira camada de dados
```

---

## 💡 Code Pronto para Usar: HERE Maps

Quer que eu **implemente HERE Maps agora**? Leva 5 minutos e você terá:
- Incidentes de tráfego (acidentes, obras)
- Fluxo de tráfego
- Severidade de congestionamento

Você concorda? Se sim, vou:
1. ✅ Criar `app/integrations/here_maps.py`
2. ✅ Atualizar `.env.example`
3. ✅ Criar novo endpoint `/routes/preview-complete`
4. ✅ Adicionar testes

**Você tem interesse?** 🚀
