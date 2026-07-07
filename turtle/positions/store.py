from dataclasses import dataclass

import psycopg2


@dataclass(frozen=True)
class Position:
    ticker: str
    name: str
    market: str
    entry_price: float
    n: float
    entry_date: str


def get_open_positions(database_url: str) -> list[Position]:
    """positions 테이블 전체 행을 조회한다 (I/O). status 컬럼이 없으므로
    행이 존재 = 보유중으로 취급한다 (매도 시 사용자가 수동으로 행을 삭제)."""
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, name, market, entry_price, n, entry_date "
                "FROM positions ORDER BY ticker"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        Position(
            ticker=row[0],
            name=row[1],
            market=row[2],
            entry_price=float(row[3]),
            n=float(row[4]),
            entry_date=row[5].isoformat(),
        )
        for row in rows
    ]
