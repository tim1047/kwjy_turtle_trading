import argparse
import logging
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # pykrx의 KRX_ID/KRX_PW, TELEGRAM_BOT_TOKEN을 임포트 전에 채운다

from swing.momentum_params import load_momentum_params
from swing.momentum_pipeline import run
from turtle.config import load_config
from turtle.data.krx import KrxFetcher


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="모멘텀 스윙 검색기")
    parser.add_argument("--date", help="YYYY-MM-DD (기본: 직전 거래일)")
    parser.add_argument(
        "--no-send", action="store_true", help="텔레그램 전송 생략, stdout만"
    )
    args = parser.parse_args()

    target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    cfg = load_config()
    params = load_momentum_params()
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
