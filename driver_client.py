#!/usr/bin/env python3
"""
Cliente de Motorista para enviar localização em tempo real
via WebSocket (SEM POLLING!)

Uso:
    python driver_client.py --driver-id "motorista123" --server ws://localhost:8000
"""

import asyncio
import json
import argparse
from urllib.parse import quote
from datetime import datetime
import websockets
from typing import Optional

class DriverLocationTracker:
    """Rastreador de localização para motorista"""
    
    def __init__(self, driver_id: str, server_url: str = "ws://localhost:8000", token: str = ""):
        self.driver_id = driver_id
        self.server_url = f"{server_url}/tracking/ws/driver/{driver_id}"
        if token:
            self.server_url += f"?token={quote(token, safe='')}"
        self.websocket = None
        self.running = False
        self.last_location = None
        self.location_change_threshold = 0.0001  # ~10 metros em graus
    
    async def connect(self):
        """Conectar ao servidor WebSocket"""
        try:
            self.websocket = await websockets.connect(self.server_url)
            print(f"✅ Motorista {self.driver_id} conectado!")
            self.running = True
        except Exception as e:
            print(f"❌ Erro ao conectar: {e}")
            self.running = False
    
    async def send_location(self, latitude: float, longitude: float, 
                           speed_kmh: Optional[float] = None,
                           heading: Optional[float] = None,
                           battery_level: Optional[float] = None,
                           signal_strength: Optional[int] = None):
        """
        Enviar localização para o servidor
        
        Args:
            latitude: Latitude
            longitude: Longitude
            speed_kmh: Velocidade em km/h
            heading: Direção (0-360 graus)
            battery_level: Nível de bateria (0-100%)
            signal_strength: Força do sinal em dBm (-120 a -25)
        """
        
        if not self.running or not self.websocket:
            return
        
        # Verificar se houve mudança significativa
        if self.last_location:
            lat_diff = abs(latitude - self.last_location['lat'])
            lon_diff = abs(longitude - self.last_location['lon'])
            
            # Se mudança é muito pequena, ignorar (economizar banda)
            if lat_diff < self.location_change_threshold and lon_diff < self.location_change_threshold:
                return
        
        # Preparar dados
        data = {
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": datetime.now().isoformat(),
        }
        
        if speed_kmh is not None:
            data["speed_kmh"] = speed_kmh
        if heading is not None:
            data["heading"] = heading
        if battery_level is not None:
            data["battery_level"] = battery_level
        if signal_strength is not None:
            data["signal_strength"] = signal_strength
        
        try:
            await self.websocket.send(json.dumps(data))
            self.last_location = {'lat': latitude, 'lon': longitude}
            print(f"📍 Localização enviada: {latitude:.4f}, {longitude:.4f} | Velocidade: {speed_kmh or 'N/A'} km/h")
        except Exception as e:
            print(f"❌ Erro ao enviar: {e}")
            self.running = False
    
    async def simulate_route(self, waypoints: list[tuple[float, float]]):
        """
        Simular uma rota com múltiplos pontos
        
        Args:
            waypoints: Lista de (latitude, longitude) para simular
        """
        
        print(f"\n🚗 Iniciando simulação de rota com {len(waypoints)} pontos")
        
        speeds = [65.4, 70.0, 65.0, 68.5, 66.0, 65.4]  # Velocidades variadas
        heading = 0
        
        for i, (lat, lon) in enumerate(waypoints):
            if not self.running:
                break
            
            speed = speeds[i % len(speeds)]
            
            # Simular movimento do heading
            heading = (heading + 5) % 360
            
            await self.send_location(
                latitude=lat,
                longitude=lon,
                speed_kmh=speed,
                heading=heading,
                battery_level=100 - (i * 2),  # Bateria diminuindo
                signal_strength=-50 - (i // 5)  # Sinal variando
            )
            
            # Aguardar 5 segundos antes da próxima atualização
            # Em um app real, isso seria acionado pelo watchPosition do geolocation
            await asyncio.sleep(5)
    
    async def start_with_demo(self):
        """Conectar e executar simulação de rota"""
        await self.connect()
        
        if not self.running:
            return
        
        # Rota: Betim → Jaboatão (simulada com 6 pontos)
        # Coordenadas reais da rota aproximada
        waypoints = [
            (-19.967279, -44.198692),  # Betim, MG (origem)
            (-19.500000, -43.500000),  # Rio de Janeiro
            (-18.000000, -40.000000),  # Espírito Santo
            (-15.000000, -39.000000),  # Bahia
            (-10.000000, -36.000000),  # Pernambuco interior
            (-8.112222, -35.01603),     # Jaboatão dos Guararapes (destino)
        ]
        
        try:
            await self.simulate_route(waypoints)
        except KeyboardInterrupt:
            print("\n⏹️  Simulação interrompida pelo usuário")
        except Exception as e:
            print(f"❌ Erro na simulação: {e}")
        finally:
            await self.disconnect()
    
    async def disconnect(self):
        """Desconectar do servidor"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            print(f"❌ Motorista {self.driver_id} desconectado")

# ============================================================================
# Exemplo: Integração com Geolocation API (para usar em um app móvel)
# ============================================================================

"""
Para usar em um app React Native ou Flutter:

### React Native Example:
```javascript
import { Geolocation } from '@react-native-camera-roll/camera-roll';

const wsRef = useRef(new WebSocket('ws://your-server/tracking/ws/driver/motorista123'));

useEffect(() => {
    const watchId = Geolocation.watchPosition(
        async (position) => {
            const { latitude, longitude, speed, heading, accuracy } = position.coords;
            
            wsRef.current.send(JSON.stringify({
                latitude,
                longitude,
                speed_kmh: speed ? speed * 3.6 : null,
                heading,
                timestamp: new Date().toISOString()
            }));
        },
        (error) => console.error(error),
        {
            enableHighAccuracy: true,
            timeout: 5000,
            maximumAge: 0,
            accuracy: {
                android: 'high',
                ios: 'best'
            }
        }
    );
    
    return () => Geolocation.clearWatch(watchId);
}, []);
```

### Flutter Example:
```dart
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:geolocator/geolocator.dart';

final channel = WebSocketChannel.connect(
    Uri.parse('ws://your-server/tracking/ws/driver/motorista123'),
);

StreamSubscription<Position> positionStream = Geolocator.getPositionStream(
    locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 10, // Atualizar a cada 10 metros
    ),
).listen((Position position) {
    channel.sink.add(jsonEncode({
        'latitude': position.latitude,
        'longitude': position.longitude,
        'speed_kmh': (position.speed * 3.6),
        'heading': position.heading,
        'timestamp': DateTime.now().toIso8601String(),
    }));
});
```
"""

async def main():
    parser = argparse.ArgumentParser(description='Cliente de Motorista para Rastreamento')
    parser.add_argument('--driver-id', default='motorista_demo', help='ID do motorista')
    parser.add_argument('--server', default='ws://localhost:8000', help='URL do servidor')
    parser.add_argument('--token', default='', help='Token configurado em TRACKING_API_KEY')
    
    args = parser.parse_args()
    
    # Criar tracker
    tracker = DriverLocationTracker(args.driver_id, args.server, args.token)
    
    # Conectar e simular rota
    await tracker.start_with_demo()

if __name__ == '__main__':
    asyncio.run(main())
