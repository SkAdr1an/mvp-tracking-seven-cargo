import pytest

from app.services.public_url import canonical_public_origin, public_trip_url


TOKEN = "A" * 43


@pytest.mark.parametrize("base,expected", [
    ("http://localhost:5174", "http://localhost:5174"),
    ("https://painel.sevencargo.com.br/", "https://painel.sevencargo.com.br"),
    ("https://painel.sevencargo.com.br/viagem/", "https://painel.sevencargo.com.br"),
])
def test_canonical_public_origin(base, expected):
    assert canonical_public_origin(base) == expected


@pytest.mark.parametrize("base", [
    "painel.sevencargo.com.br", "https://http://190.2.184.66", "ftp://example.com",
    "https://user:password@example.com", "https://example.com/other",
])
def test_rejects_malformed_public_origin(base):
    with pytest.raises(ValueError):
        canonical_public_origin(base)


def test_public_trip_url_has_one_protocol_and_canonical_domain():
    result = public_trip_url("https://painel.sevencargo.com.br/", TOKEN)
    assert result == f"https://painel.sevencargo.com.br/viagem/{TOKEN}"
    assert "https://http" not in result
