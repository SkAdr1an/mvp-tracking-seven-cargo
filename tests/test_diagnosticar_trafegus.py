from diagnosticar_trafegus import _describe, _sanitize


def test_sanitize_hides_sensitive_values_and_keeps_operational_data():
    payload = {
        "motorista": "João da Silva",
        "cpf_motorista": "00000000000",
        "token": "segredo",
        "renavam": "00000000000",
        "chassi": "ABC123",
        "rota": "BETIM/MG X JABOATÃO/PE",
        "veiculo": {"placa": "TDT5E90", "documento_transportador": "123"},
    }

    safe = _sanitize(payload)

    assert safe["motorista"] == "João da Silva"
    assert safe["cpf_motorista"] == "[OCULTO]"
    assert safe["token"] == "[OCULTO]"
    assert safe["renavam"] == "[OCULTO]"
    assert safe["chassi"] == "[OCULTO]"
    assert safe["rota"] == "BETIM/MG X JABOATÃO/PE"
    assert safe["veiculo"]["documento_transportador"] == "[OCULTO]"


def test_describe_reports_list_shape_without_values():
    schema = _describe({"viagens": [{"codigo": 528, "status": "FINALIZADA"}]})

    assert schema["viagens"]["tipo"] == "lista"
    assert schema["viagens"]["quantidade"] == 1
    assert schema["viagens"]["estrutura_primeiro_item"]["codigo"] == "int"
