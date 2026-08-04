from dataclasses import dataclass


@dataclass(frozen=True)
class RouteProfile:
    key: str
    name: str
    origin: str
    destination: str
    coordinates: tuple[tuple[float, float], ...]
    source: str


# Corredor amostrado da geometria de 21.208 pontos do mapa Trafegus fornecido
# pela operação. Os pontos permanecem na ordem original e servem como controles
# obrigatórios; não representam paradas físicas.
BETIM_JABOATAO = RouteProfile(
    key="trafegus_betim_jaboatao",
    name="Trafegus · Betim → Jaboatão",
    origin="CEVA_SHOPEE - BETIM/MG",
    destination="CEVA_SHOPEE - JABOATÃO DOS GUARARAPES/PE",
    coordinates=(
        (-19.98082, -44.26609), (-19.62398, -44.20493),
        (-18.88302, -44.37696), (-17.71968, -44.09348),
        (-16.77863, -43.84030), (-16.43387, -43.28016),
        (-16.13445, -42.26071), (-15.42600, -41.21808),
        (-14.41082, -40.35328), (-13.56847, -40.07809),
        (-12.68457, -39.67942), (-12.34793, -38.77059),
        (-11.78642, -37.95009), (-11.23254, -37.42690),
        (-10.72653, -37.07673), (-10.11809, -36.78230),
        (-9.80045, -36.11155), (-9.28199, -35.80227),
        (-8.80103, -35.62505), (-8.44920, -35.35061),
        (-8.20771, -34.96259),
    ),
    source="geometry_imported_from_trafegus_map",
)

ROUTE_PROFILES = {BETIM_JABOATAO.key: BETIM_JABOATAO}


def get_route_profile(key: str | None) -> RouteProfile | None:
    return ROUTE_PROFILES.get(key or "")
