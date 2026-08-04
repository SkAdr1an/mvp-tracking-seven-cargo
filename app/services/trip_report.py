from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.journey_observation import get_journey_observation_service
from app.storage.operations import OperationsRepository


@dataclass(frozen=True)
class GeneratedReport:
    html_path: str
    json_path: str
    pdf_path: str | None
    generated_at: str
    sha256: str
    evidence_level: str


class TripReportService:
    def __init__(self, repository: OperationsRepository, output_directory: str | Path) -> None:
        self.repository = repository
        self.output_directory = Path(output_directory).resolve()

    def evidence(self, trip_key: str) -> dict[str, Any]:
        trip = self.repository.trip(trip_key)
        if not trip:
            raise KeyError(trip_key)
        observation = get_journey_observation_service(self.repository)
        positions = self.repository.position_history(trip_key, 10000)
        plan = self.repository.plan(trip_key)
        diagnostic = self.repository.diagnostic(trip_key)
        route = self.repository.route(trip["route_id"]) if trip.get("route_id") else None
        stops = observation.stops(trip_key)
        gaps = observation.gaps(trip_key)
        delay = diagnostic.get("commitment_delta_minutes") if diagnostic else None
        sufficient = bool(
            (plan and (plan.get("customer_commitment_at") or plan.get("scheduled_arrival_at")))
            and (trip.get("arrived_destination_at") or diagnostic and diagnostic.get("eta_at"))
        )
        return {
            "trip": trip,
            "route": route,
            "plan": plan,
            "diagnostic": diagnostic,
            "eta_history": self.repository.eta_history(trip_key, 1000),
            "events": self.repository.events(trip_key),
            "positions": positions,
            "stops": stops,
            "communication_gaps": gaps,
            "summary": {
                "position_count": len(positions),
                "stop_count": len(stops),
                "attention_count": sum(item["classification"] == "ATTENTION" for item in stops),
                "urgent_count": sum(item["classification"] == "URGENT" for item in stops),
                "observed_stop_minutes": round(sum(item["duration_minutes"] for item in stops), 1),
                "communication_gap_minutes": round(sum(item["duration_minutes"] for item in gaps), 1),
                "delay_minutes": delay if sufficient else None,
                "delay_evidence": "CALCULATED" if sufficient else "UNAVAILABLE",
                "confidence": "HIGH" if sufficient and positions else "LIMITED",
            },
            "methodology": {
                "stop_radius_m": 250,
                "communication_gap_threshold_minutes": 20,
                "overlap_policy": "Communication gaps are never counted as observed stops",
            },
        }

    def generate(self, trip_key: str) -> GeneratedReport:
        evidence = self.evidence(trip_key)
        generated = datetime.now(timezone.utc)
        safe_key = hashlib.sha256(trip_key.encode()).hexdigest()[:12]
        directory = self.output_directory / safe_key
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "evidence.json"
        html_path = directory / "report.html"
        self._atomic_write(json_path, json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
        rendered = self._render(evidence, generated)
        self._atomic_write(html_path, rendered)
        pdf_path: str | None = None
        try:
            from app.services.pdf_renderer import render_html_to_pdf

            pdf_path = str(render_html_to_pdf(html_path))
        except Exception:
            # HTML and evidence remain authoritative when a browser is unavailable.
            pdf_path = None
        return GeneratedReport(
            html_path=str(html_path), json_path=str(json_path), pdf_path=pdf_path,
            generated_at=generated.isoformat(),
            sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            evidence_level=evidence["summary"]["delay_evidence"],
        )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _render(value: dict[str, Any], generated: datetime) -> str:
        trip, route, summary = value["trip"], value["route"], value["summary"]
        delay = (
            f'{summary["delay_minutes"]:.0f} minutos'
            if summary["delay_minutes"] is not None else "Indisponível"
        )
        cards = "".join(
            f"<article><small>{html.escape(label)}</small><strong>{html.escape(str(number))}</strong></article>"
            for label, number in (
                ("Posições", summary["position_count"]), ("Paradas", summary["stop_count"]),
                ("Atenção", summary["attention_count"]), ("Urgência", summary["urgent_count"]),
                ("Tempo parado", f'{summary["observed_stop_minutes"]:.0f} min'),
                ("Atraso", delay),
            )
        )
        stops = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(item))}</td>" for item in (
                stop["classification"], stop["started_at"], stop.get("ended_at") or "Em aberto",
                f'{stop["duration_minutes"]:.0f} min', stop.get("reason_text") or "Motivo não registrado",
            )) + "</tr>" for stop in value["stops"]
        ) or '<tr><td colspan="5">Nenhuma parada persistida.</td></tr>'
        return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>
<title>Relatório operacional</title><style>
body{{font:14px Arial;color:#172033;max-width:1000px;margin:36px auto;padding:0 24px}}
header{{background:#12395b;color:white;padding:32px;border-radius:12px}}h1{{margin:0}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}}
article{{padding:16px;border:1px solid #dbe3ea;border-radius:9px}}small,strong{{display:block}}strong{{font-size:22px;margin-top:8px}}
.warning{{background:#fff4d6;border-left:5px solid #e4a300;padding:14px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#12395b;color:white}}
@page{{size:A4;margin:12mm}}@media print{{body{{margin:0;padding:0;max-width:none;-webkit-print-color-adjust:exact;print-color-adjust:exact}}header,article,table,.warning{{break-inside:avoid}}h2{{break-after:avoid}}thead{{display:table-header-group}}tr{{break-inside:avoid}}}}
</style></head><body><header><small>Seven Cargo · Relatório automático</small>
<h1>{html.escape(trip.get('current_driver') or 'Motorista não informado')}</h1>
<p>{html.escape(trip['plate'])} · {html.escape(route['name'] if route else 'Rota não associada')}</p></header>
<section class='cards'>{cards}</section>
<div class='warning'><b>Evidência do atraso: {summary['delay_evidence']}</b><br>
O relatório diferencia dados persistidos, cálculos e informações indisponíveis.</div>
<h2>Paradas observadas</h2><table><thead><tr><th>Classificação</th><th>Início</th><th>Fim</th><th>Duração</th><th>Motivo</th></tr></thead><tbody>{stops}</tbody></table>
<h2>Fontes e método</h2><p>{summary['position_count']} posições persistidas; paradas em raio de 250 m; lacunas acima de 20 minutos não entram no tempo parado.</p>
<footer>Gerado em {generated.isoformat()} · nível de confiança {summary['confidence']}</footer></body></html>"""
