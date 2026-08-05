import asyncio
import httpx
import json
from datetime import datetime, timedelta
from enum import Enum

class DriverProfile(Enum):
    """Perfis de motorista para análise de rota"""
    CONSERVADOR = {"speed_reduction": 1.2, "desc": "Motorista conservador (reduz velocidade)"}
    MEDIANO = {"speed_reduction": 1.0, "desc": "Motorista mediano (velocidade padrão)"}
    AGRESSIVO = {"speed_reduction": 0.8, "desc": "Motorista agressivo (aumenta velocidade)"}

async def test_route():
    """Teste de rota com análise completa"""
    
    # Usar horário atual + 2 horas para departure
    now = datetime.now()
    departure_time = (now + timedelta(hours=2)).replace(microsecond=0)
    
    payload = {
        "origin": "Betim, MG, Brasil",
        "destination": "Jaboatão dos Guararapes, PE, Brasil",
        "departure_at": departure_time.isoformat() + "-03:00"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("=" * 80)
        print("🚚 TESTE DE ROTA - MOTORISTA MEDIANO")
        print("=" * 80)
        print(f"\n📅 Horário da Requisição: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"📍 Origem: {payload['origin']}")
        print(f"📍 Destino: {payload['destination']}")
        print(f"🚗 Horário de Partida: {departure_time.strftime('%d/%m/%Y %H:%M:%S')} (BRT/BRST)")
        
        response = await client.post(
            "http://127.0.0.1:8000/routes/preview",
            json=payload,
            timeout=30.0
        )
        
        if response.status_code != 200:
            print(f"\n❌ Erro na requisição: {response.status_code}")
            print(response.text)
            return
        
        data = response.json()
        
        print("\n" + "=" * 80)
        print("📊 INFORMAÇÕES DA ROTA")
        print("=" * 80)
        
        # Origem
        print(f"\n🔴 ORIGEM:")
        print(f"   Endereço: {data['origin']['address']}")
        print(f"   Latitude: {data['origin']['position'].get('lat', 'N/A')}")
        print(f"   Longitude: {data['origin']['position'].get('lon', 'N/A')}")
        
        # Destino
        print(f"\n🔵 DESTINO:")
        print(f"   Endereço: {data['destination']['address']}")
        print(f"   Latitude: {data['destination']['position'].get('lat', 'N/A')}")
        print(f"   Longitude: {data['destination']['position'].get('lon', 'N/A')}")
        
        # Distância
        distance_km = data['distance_km']
        print(f"\n📏 DISTÂNCIA:")
        print(f"   {distance_km:,.2f} km")
        print(f"   {distance_km * 0.621371:,.2f} milhas")
        
        # Tempos
        duration_no_traffic = data['duration_without_traffic_minutes']
        duration_with_traffic = data['duration_with_traffic_minutes']
        traffic_delay = data['traffic_delay_minutes']
        
        print(f"\n⏱️  TEMPOS:")
        print(f"   Tempo sem tráfico: {int(duration_no_traffic // 60):02d}h {int(duration_no_traffic % 60):02d}min ({duration_no_traffic:.1f} min)")
        print(f"   Tempo com tráfico: {int(duration_with_traffic // 60):02d}h {int(duration_with_traffic % 60):02d}min ({duration_with_traffic:.1f} min)")
        print(f"   Atraso por tráfico: {traffic_delay:.1f} minutos ({traffic_delay/60:.1f} horas)")
        
        if traffic_delay > 0:
            delay_percentage = (traffic_delay / duration_no_traffic) * 100
            print(f"   Tráfico representa {delay_percentage:.1f}% do tempo total")
        
        # Velocidade média
        avg_speed_kmh = distance_km / (duration_with_traffic / 60)
        avg_speed_mph = avg_speed_kmh * 0.621371
        print(f"\n🏎️  VELOCIDADE MÉDIA (com tráfico):")
        print(f"   {avg_speed_kmh:.1f} km/h")
        print(f"   {avg_speed_mph:.1f} mph")
        
        # Chegada estimada
        departure_dt = datetime.fromisoformat(data['departure_at'])
        arrival_dt = datetime.fromisoformat(data['estimated_arrival_at'])
        
        print(f"\n🕐 HORÁRIOS:")
        print(f"   Partida: {departure_dt.strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"   Chegada: {arrival_dt.strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"   Diferença: {(arrival_dt - departure_dt).total_seconds() / 3600:.1f} horas")
        
        # Status e análise
        status_icon = {"normal": "🟢", "attention": "🟡", "critical": "🔴"}
        status_text = {
            "normal": "Tráfico leve - Viagem normal",
            "attention": "Tráfico moderado - Atenção",
            "critical": "Tráfico pesado - Crítico"
        }
        
        print(f"\n{status_icon.get(data['status'], '⚪')} STATUS DA ROTA: {status_text.get(data['status'], 'Desconhecido')}")
        print(f"   Classificação: {data['status'].upper()}")
        
        # Análise para motorista mediano
        print("\n" + "=" * 80)
        print("🧑‍🚗 ANÁLISE PARA MOTORISTA MEDIANO")
        print("=" * 80)
        
        profile = DriverProfile.MEDIANO
        
        print(f"\n👤 Perfil: {profile.value['desc']}")
        print(f"\n💡 RECOMENDAÇÕES:")
        
        if traffic_delay < 20:
            print(f"   ✅ Tráfico leve - Viagem tranquila")
            print(f"   ✅ Sem necessidade de alterações no itinerário")
            print(f"   💪 Pode manter velocidade padrão")
        elif traffic_delay < 60:
            print(f"   ⚠️  Tráfico moderado - Prepare-se para atrasos")
            print(f"   ⏰ Aumento de {traffic_delay:.0f} minutos no tempo total")
            print(f"   🛣️  Considere partir um pouco mais cedo")
            print(f"   📱 Tenha app de navegação atualizado")
        else:
            print(f"   🔴 Tráfico pesado - Viagem pode ter congestionamentos")
            print(f"   ⏰ Aumento de {traffic_delay/60:.1f} horas no tempo total")
            print(f"   ⚡ Considere partir bem mais cedo")
            print(f"   🛣️  Procure rotas alternativas")
        
        # Combustível e custos (estimativa)
        fuel_consumption_l_per_100km = 25  # caminhão médio
        fuel_liters = (distance_km / 100) * fuel_consumption_l_per_100km
        fuel_price_per_liter = 6.50  # Preço aproximado do diesel
        fuel_cost = fuel_liters * fuel_price_per_liter
        
        print(f"\n⛽ ESTIMATIVA DE COMBUSTÍVEL (Diesel):")
        print(f"   Consumo: ~{fuel_consumption_l_per_100km} L/100km")
        print(f"   Total estimado: {fuel_liters:.1f} litros")
        print(f"   Custo (R$ {fuel_price_per_liter:.2f}/L): R$ {fuel_cost:.2f}")
        
        # Pausas recomendadas
        driving_hours = duration_with_traffic / 60
        pauses_recommended = max(1, int(driving_hours / 4))
        
        print(f"\n🛑 PAUSAS RECOMENDADAS:")
        print(f"   Duração da viagem: {driving_hours:.1f} horas")
        print(f"   Pausas recomendadas: {pauses_recommended} pausa(s)")
        print(f"   Frequência: A cada ~{driving_hours/pauses_recommended:.0f} horas")
        
        # Informações técnicas
        print("\n" + "=" * 80)
        print("🔧 INFORMAÇÕES TÉCNICAS")
        print("=" * 80)
        print(f"\nDados brutos da resposta:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

asyncio.run(test_route())
