# 코인(크립토) 자산군 지원 — 설계 문서

**작성일**: 2026-07-08
**선행 문서**: [2026-07-06-turtle-screening-design.md](2026-07-06-turtle-screening-design.md) (MVP 제외 항목 "가상자산" 후속 구현)
**상태**: 설계 확정, 구현 계획 대기

---

## 1. 목적 및 범위

기존 주식/ETF 스크리닝 파이프라인에 코인(업비트) 자산군을 추가한다. 주식과 달리 유니버스 필터링(시총·거래대금 기준 자동 선정) 없이, 사용자가 config에 직접 지정한 소수 티커만 매일 체크한다. 손절 체크(`run_stoploss_check`)도 코인 보유 포지션을 포함한다.

### 포함
- Upbit 공개 API 기반 일봉 OHLCV 조회 (`UpbitFetcher`)
- config에 지정한 고정 티커 리스트만 스크리닝 (유니버스 자동 필터링 없음)
- 기존 스크리닝 로직(55일 돌파/20일 저점/ADX/SMA200) 그대로 재사용
- 코인 보유 포지션 손절 체크 (기존 `positions` 테이블, 스키마 변경 없음)
- 매매 파라미터의 소수점 수량 지원 (코인은 정수 개수로 매매 불가)
- 텔레그램 리포트에 코인 섹션/수량 반영

### 제외 (후순위)
- 코인 전용 신호 기준 (24시간 변동성, 상한가/하한가 없음 등 고려한 별도 로직)
- 코인 자동 유니버스 스크리닝(거래대금 상위 등 필터링)
- Upbit 외 거래소(Bithumb/Binance) 지원

---

## 2. 확정된 핵심 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| 거래소 | Upbit 공개 API (`/v1/candles/days`) | 국내 원화마켓 최대 거래소, 무료·무인증 |
| 대상 종목 | `config.yaml`의 `filters_crypto.tickers` 고정 리스트 | 사용자가 직접 소수 종목만 관리, 유니버스 자동 필터링 불필요 |
| 스크리닝 로직 | 주식/ETF와 동일 (`screen_ticker` 재사용) | 터틀 시스템 2 규칙 자체는 자산군 무관 |
| target 날짜 | 항상 `date.today()` (KRX 영업일 보정 미적용) | 코인은 365일 24시간 거래, 영업일 개념 없음 |
| 손절 체크 대상 | 포함 (`positions.market='CRYPTO'` 행 추가로 지원) | `positions` 테이블에 이미 `market` 컬럼 존재, 스키마 변경 불필요 |
| 매매 수량 단위 | 소수점 지원 (`min_unit` 자산군별 파라미터화) | 코인은 정수 개수 매매 불가 (예: 0.0012 BTC) |
| 저장소 | 없음 (무상태, 기존 원칙 유지) | 티커 리스트는 config에서만 관리 |

---

## 3. 아키텍처

### 3.1 모듈 변경/추가
```
turtle/
  config.py            # CryptoFilterConfig(tickers: list[str], min_unit: float) dataclass 추가, Config.filters_crypto 필드
  data/
    upbit.py            # 신규: UpbitFetcher(DataFetcher), normalize_upbit_ohlcv
  trading_params.py     # min_unit 파라미터화 (floor → min_unit 단위 반올림)
  pipeline.py           # crypto 블록 구현, fetcher를 dict로 라우팅
  report/telegram.py    # crypto count, 소수점 수량 포맷(_fmt_qty) 추가
  main.py               # fetchers dict 구성
config.yaml              # filters_crypto.tickers 예시값 추가, assets.crypto: true
```

### 3.2 데이터 레이어 — `UpbitFetcher`
- `GET https://api.upbit.com/v1/candles/days?market={ticker}&count={n}` (인증 불필요).
- 응답은 최신순 내림차순 → 오름차순 정렬 후 표준 스키마(open/high/low/close/volume)로 매핑.
- 기존 `with_retry` 재사용, throttle(예 0.15초) 적용해 rate limit 대응.
- `ticker` 포맷은 Upbit 규격 그대로 사용 (예: `"KRW-BTC"`) — 종목명 별도 조회 API 없으므로 리포트에는 ticker를 name으로도 사용.

### 3.3 Config
```yaml
filters_crypto:
  tickers: ["KRW-BTC", "KRW-ETH", "KRW-XRP"]   # 예시, 사용자가 추후 갱신
  min_unit: 0.0001                              # 최소 매매 단위 (코인 수량)

assets:
  crypto: true
```
`min_unit`은 주식/ETF의 암묵적 기본값 `1.0`(정수 주)과 대비되는 코인 전용 값이다.

### 3.4 Pipeline — fetcher 라우팅
- `run()` / `run_stoploss_check()` 시그니처: 단일 `fetcher: DataFetcher` → `fetchers: dict[str, DataFetcher]` (`{"STOCK": ..., "ETF": ..., "CRYPTO": ...}`).
- `run()` crypto 블록:
  ```python
  if cfg.assets.get("crypto"):
      crypto_target = date.today().strftime("%Y%m%d")
      counts["crypto"] = len(cfg.filters_crypto.tickers)
      for t in cfg.filters_crypto.tickers:
          try:
              df = fetchers["CRYPTO"].get_ohlcv(t, lookback_start(crypto_target, 520), crypto_target)
              results.append(screen_ticker(t, t, "CRYPTO", df, cfg))
          except Exception as exc:
              log.warning("코인 스크리닝 실패 %s: %s", t, exc)
  ```
- `run_stoploss_check()`: 포지션마다 `fetchers[p.market]`로 fetcher 선택 (`STOCK`/`ETF` → KrxFetcher, `CRYPTO` → UpbitFetcher).

### 3.5 매매 파라미터 — 소수점 수량
- `compute_trading_params(entry_trigger, n, account, min_unit=1.0)`의 내부 계산을 `math.floor(risk_budget/n)` → `math.floor(risk_budget/n/min_unit) * min_unit`로 변경.
- `screen_ticker(...)`가 `market == "CRYPTO"`일 때 `cfg.filters_crypto.min_unit`을, 그 외엔 `1.0`을 `compute_trading_params`에 전달.

### 3.6 리포트
- `format_report`의 `universe_counts`에 `crypto` 키 추가, 상단 요약 라인에 "코인 N개" 표기.
- `_fmt_won`(정수 원화 포맷)은 수량 표기에 부적합 → 수량 전용 `_fmt_qty(v, market)` 추가: `market == "CRYPTO"`면 소수점(최대 8자리, trailing zero 제거) 표기, 그 외엔 기존 정수 "주" 표기 유지.
- 카드 문구 "1유닛 X주" → 코인은 "1유닛 X개"로 분기.

### 3.7 main.py
```python
fetchers = {"STOCK": KrxFetcher(), "ETF": KrxFetcher(), "CRYPTO": UpbitFetcher()}
stoploss_text = run_stoploss_check(target, cfg, fetchers, send=not args.no_send)
scan_text = run(target, cfg, fetchers, send=not args.no_send)
```

---

## 4. 에러 처리
- 기존 원칙 유지: 종목별 예외는 로그만 남기고 배치 진행 격리 (`try/except` per ticker, 기존 stocks/etf 블록과 동일 패턴).
- Upbit API 실패(rate limit, 네트워크)도 `with_retry`(3회, exponential backoff)로 우선 흡수, 그래도 실패하면 해당 티커만 스킵.

## 5. 테스트 관점
- `UpbitFetcher`/`normalize_upbit_ohlcv`: raw JSON → 표준 스키마 변환 단위 테스트 (mock 응답 사용, 실 API 호출 없음).
- `compute_trading_params`: `min_unit` 상이한 값(1.0 vs 0.0001)에서 floor 동작 검증.
- `pipeline.run`: `fetchers` dict 라우팅, crypto 블록이 `assets.crypto=False`일 때 스킵되는지.
- `pipeline.run_stoploss_check`: `market` 별 fetcher 선택 라우팅.
- `report.format_report`/`_fmt_qty`: 코인 소수점 수량 포맷 검증.

---

## 6. 미해결 / 후속 과제
- 코인 종목명 표시(ticker 그대로 대신 "비트코인" 등 한글명) — 필요 시 Upbit `/v1/market/all` 매핑 추가.
- 코인 전용 신호 기준 재검토(24시간 변동성 특성).
- Bithumb/Binance 등 멀티 거래소 확장.
