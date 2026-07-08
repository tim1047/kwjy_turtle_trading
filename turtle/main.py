import argparse
import logging
from datetime import datetime

# pykrx 인증은 turtle/main.py 기존 주석 그대로 유지
from dotenv import load_dotenv

load_dotenv()

from turtle.config import load_config
from turtle.data.krx import KrxFetcher
from turtle.data.upbit import UpbitFetcher
from turtle.pipeline import run, run_stoploss_check


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="터틀 트레이딩 일일 스크리닝")
    parser.add_argument("--date", help="YYYY-MM-DD (기본: 직전 거래일)")
    parser.add_argument(
        "--no-send", action="store_true", help="텔레그램 전송 생략, stdout만"
    )
    args = parser.parse_args()

    target = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    )
    cfg = load_config()
    krx_fetcher = KrxFetcher()
    fetchers = {
        "STOCK": krx_fetcher,
        "ETF": krx_fetcher,
        "CRYPTO": UpbitFetcher(),
    }

    stoploss_text = run_stoploss_check(target, cfg, fetchers, send=not args.no_send)
    print(stoploss_text)

    scan_text = run(target, cfg, fetchers, send=not args.no_send)
    print(scan_text)


if __name__ == "__main__":
    main()
