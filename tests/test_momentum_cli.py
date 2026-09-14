"""momentum_main CLI 인자 처리 테스트."""

from datetime import date
from unittest.mock import patch

import pytest

from swing.momentum_main import main


def _cfg():
    class _C:
        database_url = "db"
        telegram_bot_token = "token"
        telegram_chat_id = "chat"

    return _C()


def _invoke(argv):
    with patch("swing.momentum_main.load_config", return_value=_cfg()), \
         patch("swing.momentum_main.KrxFetcher"), \
         patch("swing.momentum_main.run", return_value="일일리포트") as run_mock, \
         patch("swing.momentum_main.run_range", return_value="기간리포트") as range_mock:
        main(argv)
    return run_mock, range_mock


def test_single_date_uses_daily_run():
    run_mock, range_mock = _invoke(["--date", "2026-07-11", "--no-send"])
    run_mock.assert_called_once()
    range_mock.assert_not_called()
    assert run_mock.call_args.args[0] == date(2026, 7, 11)


def test_start_end_uses_range_run():
    run_mock, range_mock = _invoke(["--start", "2026-07-01", "--end", "2026-07-11"])
    range_mock.assert_called_once()
    run_mock.assert_not_called()
    assert range_mock.call_args.args[:2] == (date(2026, 7, 1), date(2026, 7, 11))


def test_date_with_start_is_rejected():
    with pytest.raises(SystemExit):
        _invoke(["--date", "2026-07-11", "--start", "2026-07-01", "--end", "2026-07-11"])


def test_start_without_end_is_rejected():
    with pytest.raises(SystemExit):
        _invoke(["--start", "2026-07-01"])


def test_end_before_start_is_rejected():
    with pytest.raises(SystemExit):
        _invoke(["--start", "2026-07-11", "--end", "2026-07-01"])
