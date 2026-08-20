from datetime import date
from unittest.mock import MagicMock, patch

from swing.momentum_positions import MomentumPosition, get_open_positions


@patch("swing.momentum_positions.psycopg2.connect")
def test_get_open_positions_maps_rows_to_position(mock_connect):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("005930", "삼성전자", "KOSPI", 75000.0, 56250.0, 10, date(2026, 8, 1)),
        ("069500", "KODEX 200", "KOSPI", 32000.0, 24000.0, 15, date(2026, 8, 3)),
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    result = get_open_positions("postgresql://fake")

    assert result == [
        MomentumPosition(
            ticker="005930", name="삼성전자", market="KOSPI",
            entry_price=75000.0, stop_price=56250.0, hold_days=10,
            entry_date="2026-08-01",
        ),
        MomentumPosition(
            ticker="069500", name="KODEX 200", market="KOSPI",
            entry_price=32000.0, stop_price=24000.0, hold_days=15,
            entry_date="2026-08-03",
        ),
    ]
    mock_conn.close.assert_called_once()


@patch("swing.momentum_positions.psycopg2.connect")
def test_get_open_positions_empty(mock_connect):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    assert get_open_positions("postgresql://fake") == []
