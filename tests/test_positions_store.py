from datetime import date
from unittest.mock import MagicMock, patch

from turtle.positions.store import Position, get_open_positions


@patch("turtle.positions.store.psycopg2.connect")
def test_get_open_positions_maps_rows_to_position(mock_connect):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("005930", "삼성전자", "STOCK", 75000.0, 1500.25, date(2026, 7, 1)),
        ("069500", "KODEX 200", "ETF", 32000.0, 400.0, date(2026, 7, 3)),
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    result = get_open_positions("postgresql://fake")

    assert result == [
        Position(
            ticker="005930", name="삼성전자", market="STOCK",
            entry_price=75000.0, n=1500.25, entry_date="2026-07-01",
        ),
        Position(
            ticker="069500", name="KODEX 200", market="ETF",
            entry_price=32000.0, n=400.0, entry_date="2026-07-03",
        ),
    ]
    mock_conn.close.assert_called_once()
