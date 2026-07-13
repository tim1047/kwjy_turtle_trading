# Chandelier Exit (3번째 손절 레이어) 설계

## 배경

`docs/enhancement_roadmap.md` 3번 항목. 현재 2단 손절(2N 재난 방지 / 10일 저가
추세종료) 위에 `최고가(22일) - 3×ATR` ratchet(스톱이 올라가기만 함) 스탑을
추가해 큰 이익 포지션의 반납을 방지한다. 백테스트 엔진(`turtle/backtest.py`,
`2026-07-13-backtest-engine-design.md`)이 이미 있어 도입 전 성과 검증이 가능함.

## 범위

백테스트 경로와 실거래 경로(DB 영속화 포함) **동시 구현**. 백테스트만 먼저
검증하는 게 로드맵 0순위 원칙과 더 맞지만, 사용자가 두 경로 동시 진행을
선택함 — 실거래 경로는 임계값(3×ATR, 22일) 튜닝이 끝나기 전까지는 알림에만
쓰이고 자동 매매를 트리거하지 않으므로 리스크는 제한적.

## 핵심 결정

- **ATR 소스**: 진입 시점 고정 N(`position.n`)이 아니라 매번 최신 df로
  재계산하는 현재 ATR(`ind.atr_20`, 기존 Wilder RMA) 사용. 고전 Chandelier
  Exit 공식이 현재 변동성 기준이고, 기존 10일 저가 스탑도 매번 재계산하는
  방식이라 일관성 있음.
- **윈도우/배수는 하드코드**: 기존 55/20/10/200일 윈도우가 전부
  `indicators.py`/`signals.py`에 리터럴로 박혀있는 컨벤션을 따름 —
  `AccountConfig`에 넣지 않음. 22일 고가, 3배 배수 고정.
- **새 지표 모듈 안 만듦**: `high_22`만 `IndicatorResult`에 추가하고,
  `high_22 - 3 * atr_20` 계산은 호출부에 인라인 (기존 `2 * position.n`
  스타일과 동일).
- **ratchet 상태**:
  - 백테스트: `OpenPosition.chandelier_stop` (메모리, mutable 필드 — 기존
    `stop_price`와 동일 패턴)
  - 실거래: DB 컬럼 `chandelier_stop` 신규 (`positions` 테이블), 매 체크마다
    `max(신규계산값, 기존값)`로 갱신 후 다시 저장. **이 프로젝트 첫 write-back
    경로** — 지금까지 `pipeline.py`의 스탑 체크는 읽기 전용이었음.

## 아키텍처

### `turtle/indicators.py`
- `IndicatorResult`에 `high_22: float` 필드 추가.
- `compute_indicators()`에서 `rolling_high(df["high"], 22)` 계산해 채움.

### `turtle/backtest.py`
- `OpenPosition`에 `chandelier_stop: float` 필드 추가.
- `enter_position()`: 진입 시 `ind.high_22 - 3 * ind.atr_20`으로 초기화.
- `run_backtest()` 루프: 포지션 보유 중 매일
  `position.chandelier_stop = max(position.chandelier_stop, ind.high_22 - 3 * ind.atr_20)`
  갱신 (피라미딩 유닛 추가와 무관하게 매일 갱신).
- `check_exit()`: `breach_chandelier = close <= position.chandelier_stop` 추가.
  기존 2-플래그 if/elif 체인을 3-플래그 리스트+join으로 일반화:
  ```python
  reasons = []
  if breach_2n:
      reasons.append("2N")
  if breach_10d:
      reasons.append("10D")
  if breach_chandelier:
      reasons.append("CHANDELIER")
  if not reasons:
      return None
  reason = "+".join(reasons)
  ```

### `db/positions.sql` + `turtle/positions/store.py`
- DDL에 `chandelier_stop NUMERIC(15,2)` 컬럼 추가 (nullable, 기존 행은 NULL —
  마이그레이션 시 별도 백필 불필요, 다음 체크 때 첫 계산값이 baseline이 됨).
  마이그레이션은 기존 컨벤션대로 사용자가 수동 `ALTER TABLE` 실행, 이 저장소엔
  문서화만 함.
- `Position`에 `chandelier_stop: float | None` 추가, `get_open_positions()`
  SELECT에 컬럼 포함.
- 신규 함수 `update_chandelier_stop(database_url: str, ticker: str, value: float) -> None`
  (I/O, `UPDATE positions SET chandelier_stop = %s WHERE ticker = %s`).

### `turtle/stoploss.py`
- `check_position()`은 순수함수 유지. 내부에서 `compute_indicators(df)` 호출해
  `high_22`/`atr_20` 재사용(직접 rolling/ATR 재구현 안 함).
  ```python
  candidate = ind.high_22 - 3 * ind.atr_20
  new_stop = candidate if position.chandelier_stop is None else max(candidate, position.chandelier_stop)
  ```
- `StopCheckResult`에 `stop_chandelier: float`, `breach_chandelier: bool` 추가.

### `turtle/pipeline.py`
- 스탑 체크 루프(`check_position` 호출부, 현재 ~line 209)에서 성공 시
  `update_chandelier_stop(cfg.database_url, p.ticker, result.stop_chandelier)`
  호출 — I/O는 이 레이어에만, `check_position`은 계속 순수함수.
- **lookback 확대 필요**: 현재 `lookback_start(target_str, days=30)`은 10일
  저가엔 충분하지만, Wilder ATR은 주는 데이터 길이에 민감함
  (`atr_wilder`가 첫 `period`개 TR 평균으로 seed) — 30일 조각으로 계산한
  ATR은 진입/스캔 시 쓰는 긴 히스토리 ATR과 다른 값이 나옴. 스탑 체크 경로의
  lookback을 `days=520`(스캔/진입 경로가 이미 쓰는 값과 동일, `pipeline.py`의
  다른 `lookback_start` 호출들과 일치)으로 늘려 롱히스토리 ATR에 수렴하게 함
  (crypto lookback도 동일 적용). 구현 시 300일로는 스캔 경로와 값이 어긋날
  여지가 있어 520으로 정정.

### `turtle/report/telegram.py`
- `format_stoploss_report()`: 기존 "2N 이탈"/"10일저가 이탈" 플래그 옆에
  "Chandelier 이탈" 추가.

## 비범위

- 실거래 자동 매도 실행 (현재 파이프라인은 알림만 보냄, 이번 작업도 동일)
- ADX/버퍼/변동성 게이트 등 로드맵 다른 항목
- 3×ATR 배수·22일 윈도우 자체의 백테스트 기반 튜닝 (일단 로드맵 명시값 그대로
  구현, 튜닝은 이후 별도 작업)

## 에러 처리

- `update_chandelier_stop` 실패(DB 오류)는 개별 종목 실패로 로그만 남기고
  배치 중단 안 함 — 기존 `run_stoploss_check`의 "종목별 실패가 배치를 막지
  않도록" 관용과 동일 원칙.
- `check_position`이 `high_22`/`atr_20` 계산에 필요한 최소 데이터(약 21거래일)
  를 못 채우면(백필 전 신규 상장 등) `compute_indicators`가 NaN 반환 —
  이 경우 `stop_chandelier`도 NaN이 되고 `breach_chandelier`는 항상 False
  (NaN 비교) 처리. 별도 예외 처리 안 함 (기존 `sma_200` NaN 처리와 동일 관용).

## 테스트

- `tests/test_indicators.py`: `high_22` 계산 검증 (합성 OHLCV, 55/20/10과 같은
  스타일)
- `tests/test_backtest.py`: ratchet 단조증가(가격 상승 후 하락해도 스탑 유지),
  피라미딩 후에도 chandelier_stop 유지, 2N+10D+CHANDELIER 동시 breach 시
  reason 조합 문자열
- `tests/test_stoploss.py`: `check_position`의 ratchet 계산 (기존값 None →
  candidate 그대로, 기존값 있음 → max), breach_chandelier 플래그
- `tests/test_positions_store.py`: `update_chandelier_stop` (기존 mock
  psycopg2 패턴)
- `tests/test_report.py`: "Chandelier 이탈" 플래그 라인
