import asyncio

from app.api import weekly_programming
from app.api.weekly_programming import _latest_weekly_sheet


def test_latest_weekly_sheet_uses_highest_number_not_document_order():
    metadata = (
        r'[4,0,\"497031392\",[{\"1\":[[0,0,\" LHW37\"]]}]'
        r'[3,0,\"672176547\",[{\"1\":[[0,0,\" LHW38\"]]}]'
        r'[2,0,\"111\",[{\"1\":[[0,0,\"LHW12\"]]}]'
    )
    assert _latest_weekly_sheet(metadata) == ("LHW38", "672176547")


def test_latest_weekly_sheet_accepts_name_variations():
    metadata = r'[1,0,\"999\",[{\"1\":[[0,0,\" LHW_39\"]]}]'
    assert _latest_weekly_sheet(metadata) == ("LHW39", "999")


def test_source_uses_authenticated_values_and_exposes_row_colors(monkeypatch):
    class Sheets:
        spreadsheet_id = ""

        def read_latest_weekly_source(self):
            return "LHW38", [["LT", "ETA ORIGEM"], ["LT-1", "17/09/2026 10:00"]], {2: "RED"}

    monkeypatch.setattr(weekly_programming, "GoogleSheetsWriteback", Sheets)
    monkeypatch.setattr(weekly_programming, "_cache", None)
    result = asyncio.run(weekly_programming.weekly_programming_source(force=True))
    assert result["sheet_name"] == "LHW38"
    assert "LT-1" in result["csv"]
    assert result["row_colors"] == {2: "RED"}
