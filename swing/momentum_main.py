import argparse
import logging
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()  # pykrx의 KRX_ID/KRX_PW, TELEGRAM_BOT_TOKEN을 임포트 전에 채운다

from swing.momentum_params import load_momentum_params
from swing.momentum_pipeline import run, run_range
from turtle.config import load_config
from turtle.data.krx import KrxFetcher


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="모멘텀 스윙 검색기")
    parser.add_argument("--date", help="YYYY-MM-DD (기본: 직전 거래일)")
    parser.add_argument("--start", help="기간 스캔 시작일 YYYY-MM-DD (--end와 함께)")
    parser.add_argument("--end", help="기간 스캔 종료일 YYYY-MM-DD (--start와 함께)")
    parser.add_argument(
        "--no-send", action="store_true", help="텔레그램 전송 생략, stdout만"
    )
    args = parser.parse_args(argv)

    if bool(args.start) != bool(args.end):
        parser.error("--start와 --end는 함께 지정해야 합니다")
    if args.start and args.date:
        parser.error("--date와 --start/--end는 함께 쓸 수 없습니다")

    cfg = load_config()
    params = load_momentum_params()

    if args.start:
        start, end = _parse_date(args.start), _parse_date(args.end)
        if end < start:
            parser.error("--end가 --start보다 빠릅니다")
        # 기간 스캔은 조사용 모드다 — 청산 알림과 텔레그램 전송을 하지 않으므로
        # --no-send가 무의미하다 (swing.momentum_pipeline.run_range 참고).
        text = run_range(start, end, params, KrxFetcher())
    else:
        target = _parse_date(args.date) if args.date else None
        text = run(
            target,
            params,
            KrxFetcher(),
            cfg.database_url,
            cfg.telegram_bot_token,
            cfg.telegram_chat_id,
            send=not args.no_send,
        )
    print(text)


if __name__ == "__main__":
    main()
