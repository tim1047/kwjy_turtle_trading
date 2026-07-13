-- 보유종목 손절가 알림용 테이블. 피라미딩 없음 -> ticker가 PK (종목당 row 1개).
-- status 컬럼 없음: row 존재 = 보유중, 매도 시 사용자가 수동으로 DELETE.
-- 주의: 이 CREATE TABLE 문의 테이블명(positions)과 실제 쿼리 코드
-- (turtle/positions/store.py)가 쓰는 테이블명(turtle_asset)이 다르다 --
-- 기존부터 있던 불일치이며 이 파일은 신규 설치 시 참고용 DDL이다.
-- 이미 DB가 있는 경우 실제 테이블명에 맞춰 아래 ALTER TABLE 문을 조정해서 실행할 것.
CREATE TABLE positions (
    ticker      VARCHAR(20)     PRIMARY KEY,
    name        VARCHAR(100)    NOT NULL,
    market      VARCHAR(10)     NOT NULL,  -- 'STOCK' 또는 'ETF'
    entry_price NUMERIC(15,2)   NOT NULL,
    n           NUMERIC(15,4)   NOT NULL,  -- 진입 시점 ATR20, 고정값
    entry_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    chandelier_stop NUMERIC(15,2)  -- Chandelier Exit ratchet 스탑, nullable(첫 체크 전에는 NULL)
);

-- 기존 테이블(실제 이름 turtle_asset)에 컬럼만 추가하는 마이그레이션:
-- ALTER TABLE turtle_asset ADD COLUMN chandelier_stop NUMERIC(15,2);
