-- 보유종목 손절가 알림용 테이블. 피라미딩 없음 -> ticker가 PK (종목당 row 1개).
-- status 컬럼 없음: row 존재 = 보유중, 매도 시 사용자가 수동으로 DELETE.
CREATE TABLE positions (
    ticker      VARCHAR(20)     PRIMARY KEY,
    name        VARCHAR(100)    NOT NULL,
    market      VARCHAR(10)     NOT NULL,  -- 'STOCK' 또는 'ETF'
    entry_price NUMERIC(15,2)   NOT NULL,
    n           NUMERIC(15,4)   NOT NULL,  -- 진입 시점 ATR20, 고정값
    entry_date  DATE NOT NULL DEFAULT CURRENT_DATE
);
