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
    chandelier_stop: float | None = None


def get_open_positions(database_url: str) -> list[Position]:
    """positions 테이블 전체 행을 조회한다 (I/O). status 컬럼이 없으므로
    행이 존재 = 보유중으로 취급한다 (매도 시 사용자가 수동으로 행을 삭제)."""
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, name, market, entry_price, n, entry_date, chandelier_stop "
                "FROM turtle_asset ORDER BY ticker"
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
            chandelier_stop=float(row[6]) if row[6] is not None else None,
        )
        for row in rows
    ]


def update_chandelier_stop(database_url: str, ticker: str, value: float) -> None:
    """ratchet된 chandelier_stop 값을 DB에 기록한다 (I/O). value가 NaN이면
    (지표 warm-up 부족) 쓰지 않는다 — NULL로 덮어써 이전 유효값을 잃지 않기 위함."""
    if value != value:  # NaN
        return
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE turtle_asset SET chandelier_stop = %s WHERE ticker = %s",
                (value, ticker),
            )
        conn.commit()
    finally:
        conn.close()
