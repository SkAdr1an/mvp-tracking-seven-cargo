from diagnosticar_posicao import _records_for_plate, _report


def test_report_preserves_operational_data_and_hides_documents():
    result = {
        "ok": True,
        "http_status": 200,
        "data": {
            "Posicao": [{"IdPosicao": 99, "Latitude": -19.9, "chassi": "segredo"}]
        },
    }

    report = _report("ultima_posicao_veiculo", result)

    assert report["dados_seguros"]["Posicao"][0]["IdPosicao"] == 99
    assert report["dados_seguros"]["Posicao"][0]["Latitude"] == -19.9
    assert report["dados_seguros"]["Posicao"][0]["chassi"] == "[OCULTO]"


def test_records_for_plate_finds_plate_in_unknown_envelope():
    payload = {
        "success": {
            "viagens": [
                {"Placa": "AWP7D63", "Latitude": -19.9},
                {"Placa": "PYL0D91", "Latitude": -20.1},
            ]
        }
    }

    matches = _records_for_plate(payload, "AWP7D63")

    assert matches == [{"Placa": "AWP7D63", "Latitude": -19.9}]
