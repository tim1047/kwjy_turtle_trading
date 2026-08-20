from dataclasses import dataclass

import psycopg2


@dataclass(frozen=True)
class MomentumPosition:
    ticker: str
    name: str
    market: str
    entry_price: float
    stop_price: float
    hold_days: int
    entry_date: str


def get_open_positions(database_url: str) -> list[MomentumPosition]:
    """momentum_position 테이블 전체 행을 조회한다 (I/O).

    status 컬럼이 없으므로 행이 존재 = 보유중으로 취급한다 (매도 시 사용자가
    수동으로 행을 삭제 — turtle.positions.store와 동일한 설계, db/momentum_positions.sql).
    """
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, name, market, entry_price, stop_price, hold_days, entry_date "
                "FROM momentum_position ORDER BY entry_date"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        MomentumPosition(
            ticker=row[0],
            name=row[1],
            market=row[2],
            entry_price=float(row[3]),
            stop_price=float(row[4]),
            hold_days=int(row[5]),
            entry_date=row[6].isoformat(),
        )
        for row in rows
    ]
