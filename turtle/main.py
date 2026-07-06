import argparse
import logging
from datetime import datetime

# pykrx authenticates against data.krx.co.kr (KRX_ID/KRX_PW env vars) at
# import time (see pykrx.website.comm.webio module-level session init), so
# .env must be loaded before any project import that pulls in pykrx.
from dotenv import load_dotenv

load_dotenv()

from turtle.config import load_config
from turtle.data.krx import KrxFetcher
from turtle.pipeline import run


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
    fetcher = KrxFetcher()
    text = run(target, cfg, fetcher, send=not args.no_send)
    print(text)


if __name__ == "__main__":
    main()
