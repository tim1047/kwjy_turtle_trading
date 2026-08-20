-- 모멘텀 검색기 보유종목 청산 알림용 테이블. 피라미딩 없음 -> ticker가 PK.
-- 사용자가 리포트의 신규 후보를 보고 수동 매수 후 이 테이블에 직접 INSERT하고,
-- 매도 후 수동으로 DELETE한다 (turtle_asset과 동일한 설계 — row 존재 = 보유중,
-- status 컬럼 없음).
--
-- stop_price/hold_days는 진입 시점 값을 그대로 고정 저장한다. 이후 config.yaml의
-- momentum_screener 파라미터를 바꿔도 이미 보유 중인 포지션의 청산 기준은 바뀌지
-- 않는다 (docs/momentum_screener_spec.md §3.3 — 손절선은 진입 시점에 확정하고
-- 갱신하지 않는다).
CREATE TABLE momentum_position (
    ticker      VARCHAR(20)     PRIMARY KEY,
    name        VARCHAR(100)    NOT NULL,
    market      VARCHAR(10)     NOT NULL,  -- 'KOSPI' 또는 'KOSDAQ'
    entry_price NUMERIC(15,2)   NOT NULL,
    stop_price  NUMERIC(15,2)   NOT NULL,  -- 진입가 * (1 - stop_pct/100), 고정값
    hold_days   INTEGER         NOT NULL,  -- 진입 시점 hold_days 스냅샷
    entry_date  DATE            NOT NULL
);
