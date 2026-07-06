# 터틀 트레이딩 스크리닝 시스템 — 설계 문서 (MVP)

**작성일**: 2026-07-06
**원본 요구사항**: [docs/init_spec.md](../../init_spec.md)
**상태**: 설계 확정, 구현 계획 대기

---

## 1. 목적 및 범위

터틀 트레이딩 시스템 2(55일 돌파 / 20일 저점 청산)에 기반해, 국내주식·국내상장 ETF 중 매수 진입 조건에 근접했거나 발생한 종목을 매일 스크리닝하고 매매 파라미터(N/ATR, 진입가, 손절가, 유닛 수량 등)를 산출하여 텔레그램으로 전송한다.

### MVP 포함
- 국내주식 / 국내상장 ETF 유니버스 필터링
- 일일 지표 계산 (N/ATR, high_55, low_20, 기타 참고 지표)
- 신호 분류 (BREAKOUT_TODAY / BREAKOUT_CLOSE / APPROACHING / NEUTRAL / BREAKDOWN)
- 매매 파라미터 계산 (진입가, 손절가, 피라미딩가, 유닛 수량/금액)
- 텔레그램 일일 리포트 전송

### MVP 제외 (후순위)
- 가상자산(크립토) 자산군
- 직전 돌파 결과 필터 (원본 스펙 5.2, 이력 추적 필요)
- 과거 시점 재생성 (`--date`)
- 데이터/결과 영속 저장 (PG·파일 캐시)
- 리포트 내 "평균 N 추이" 등 시계열 통계
- 시스템 1(20일 돌파 / 10일 청산) 병행

---

## 2. 확정된 핵심 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| 데이터 소스 | pykrx (일봉 OHLCV, 시총, 거래대금, 관리종목 등) | 무료·무인증, 장마감 후 EOD 배치에 적합. pykrx는 ATR 등 지표 미제공 → 직접 계산 |
| 저장소 | **없음 (무상태)** | 매 실행이 원천 봉에서 결정적으로 산출. 저장 불필요 |
| ATR 계산 방식 | 매 실행마다 최근 ~300봉으로 전체 재계산 | 상태 드리프트 없음, 재현성 확보. 계산 비용 무시할 수준(ms) |
| 실행 환경 | 서버/VPS + cron | 상시 자동 실행 |
| `entry_price_assumed` | 트리거가(`high_55`) [시나리오 a] | MVP 단순화. 다음날 시가 예측(b)은 후순위 |
| 계좌값·임계값 | `config.yaml` 기본값(원본 스펙) | 하드코딩 금지 |

---

## 3. 아키텍처

### 3.1 원칙
지표·신호·매매파라미터 계산은 **순수 함수**로 분리 (I/O·전역상태 배제). 데이터 수집은 어댑터(`DataFetcher` ABC)로 추상화해 신규 자산군 추가 시 fetcher만 붙이면 되도록 한다(원본 스펙 8.5). 무상태 파이프라인이므로 각 실행은 대상일 하나에 대해 독립적으로 완결된다.

### 3.2 모듈 구조
```
turtle-trading/
  config.yaml            # 계좌값·필터임계값·자산토글·텔레그램 chat_id
  .env                   # 텔레그램 봇토큰 (하드코딩 금지)
  requirements.txt
  turtle/
    config.py            # yaml + .env 로드 → dataclass
    calendar.py          # 거래일 계산 (pykrx 영업일, 휴장일 처리)
    data/
      base.py            # DataFetcher ABC: get_ohlcv(ticker, start, end) -> DataFrame
      krx.py             # pykrx 어댑터 (주식 + ETF)
    universe/
      krx_stocks.py      # 국내주식 유니버스 필터 (원본 스펙 3.1)
      krx_etf.py         # ETF 유니버스
    indicators.py        # 순수: true_range, atr_wilder, rolling_high/low, adx
    signals.py           # 순수: classify() → 신호 상태
    trading_params.py    # 순수: unit_size, stop_loss, pyramids
    report/
      telegram.py        # 리포트 포맷 + 전송
    pipeline.py          # 오케스트레이션 (종목별 예외 격리)
    main.py              # 엔트리포인트
  tests/
    test_indicators.py
    test_signals.py
    test_trading_params.py
```

### 3.3 데이터 흐름
1. `main` → 대상일 결정 (기본: 직전 거래일)
2. 유니버스 빌드 → 자산군별 티커 리스트
3. 종목별: pykrx로 ~300봉 fetch → 지표 전체 재계산
4. 신호 분류 + 매매 파라미터 계산 (계좌 config 적용)
5. 오늘 신호·근접 종목 취합 → 텔레그램 리포트 전송

디스크·DB 접근 없음.

---

## 4. 구성요소 상세

### 4.1 config (`config.py`)
`config.yaml` + `.env` 로드 → 불변 dataclass. 계좌 설정, 필터 임계값, 옵션 필터 on/off, 자산군 토글, 텔레그램 chat_id 포함. 봇 토큰·비밀값은 `.env`에서만.

```yaml
account:
  total_value: 100000000
  risk_pct: 0.01
  max_units_per_asset: 4
  max_units_correlated: 6
  max_units_total: 12

filters:
  stocks:
    min_listing_days: 300
    min_avg_turnover_20: 10000000000   # 100억
    min_avg_volume_20: 100000          # 10만 주
    min_price: 1000
    min_market_cap: 300000000000       # 3000억
    kospi_top_n: 200
    kosdaq_top_n: 100
    exclude_preferred: true
    exclude_spac: true
    exclude_recent_split: true         # 최근 60일 액면분할/병합

signals:
  approaching_pct: 0.98                 # 트리거가 대비 2% 이내

assets:
  stocks: true
  etf: true
  crypto: false                         # MVP 제외
```

### 4.2 calendar (`calendar.py`)
pykrx 영업일 API로 거래일 계산. 대상일이 휴장일이면 직전 거래일로 보정. 지표에 필요한 조회 시작일(대상일에서 약 300거래일 전) 산출.

### 4.3 data fetcher (`data/base.py`, `data/krx.py`)
`DataFetcher` ABC: `get_ohlcv(ticker, start, end) -> DataFrame[date, open, high, low, close, volume]`. `krx.py`가 pykrx로 구현. 재시도 3회(exponential backoff), 호출 간 스로틀 sleep으로 rate limit 준수(원본 스펙 8.1/8.2).

### 4.4 universe (`universe/`)
원본 스펙 3.1 필터를 AND 조건으로 적용:
- 시총 기준 KOSPI 상위 200 / KOSDAQ 상위 100으로 후보 축소 → 상장기간 ≥300거래일, 20일 평균 거래대금 ≥100억, 20일 평균 거래량 ≥10만주, 현재가 ≥1,000원, 시총 ≥3,000억
- 관리종목·투자경고·정리매매·거래정지 제외
- 옵션 필터(config on/off): 우선주 제외, SPAC 제외, 최근 60일 액면분할/병합 제외

진입/탈락 종목은 로깅(원본 스펙 9.7).

### 4.5 indicators (`indicators.py`) — 순수 함수
| 함수 | 정의 |
|---|---|
| `true_range(df)` | max(H−L, \|H−C_prev\|, \|L−C_prev\|) |
| `atr_wilder(tr, period=20)` | 첫 20 TR의 SMA로 시드 → 21일차부터 `N = (19·N_prev + TR)/20` |
| `rolling_high(series, window, shift=1)` | `high_55` = max(High[t−55:t−1]) — **오늘 제외** |
| `rolling_low(series, window, shift=1)` | `low_20` = min(Low[t−20:t−1]) — **오늘 제외** |
| `adx(df, period=14)` | 추세 강도 참고용(표시만) |

추가 산출: `high_20`, `low_10`(시스템1 참고용), `avg_volume_20`, `avg_turnover_20`(유동성 재확인).

**불변식**: `high_55`/`low_20`는 반드시 오늘(t) 캔들을 제외한다. 포함 시 돌파 판단이 왜곡된다(원본 스펙 9.1).

### 4.6 signals (`signals.py`) — 순수 함수
`classify()` 입력(오늘 H/L/C, high_55, low_20, approaching_pct) → 상태 1개:

| 상태 | 조건 |
|---|---|
| `BREAKOUT_TODAY` | 오늘 고가 ≥ high_55 |
| `BREAKOUT_CLOSE` | 오늘 종가 ≥ high_55 |
| `APPROACHING` | 오늘 종가 ≥ high_55 × approaching_pct |
| `BREAKDOWN` | 오늘 저가 ≤ low_20 |
| `NEUTRAL` | 위 모두 미해당 |

우선순위: BREAKOUT_TODAY > BREAKOUT_CLOSE > APPROACHING > BREAKDOWN > NEUTRAL.

### 4.7 trading_params (`trading_params.py`) — 순수 함수
`entry_price_assumed = high_55` 기준으로 계산:

| 파라미터 | 계산식 |
|---|---|
| `entry_trigger` | high_55 |
| `stop_loss_price` | entry − 2N |
| `pyramid_1/2/3_price` | entry + 0.5N / 1.0N / 1.5N |
| `unit_size` | **floor**(total_value × risk_pct / N) |
| `unit_notional` | unit_size × entry |
| `max_position_notional` | 4유닛 총액(참고용) |
| `max_loss_per_unit` | unit_size × 2N |

특수 케이스: `unit_size < 1` → "매매 불가". ETF에서 0이면 "계좌 규모 부족" 경고. 유닛 수량은 항상 내림(반올림 시 리스크 초과, 원본 스펙 9.3).

### 4.8 report (`report/telegram.py`)
원본 스펙 6.1 형식으로 텔레그램 메시지 구성 후 봇 API로 전송. 구성: 요약(유니버스 수, 신호 수) / 🔥 매수 신호 종목 표 / 👀 관찰 종목(2% 이내) 표 / 📊 오늘 단면 통계(자산군별 종목 수). 텔레그램 메시지 길이 제한 고려해 표는 종목이 많으면 분할 전송.

### 4.9 pipeline (`pipeline.py`) + main (`main.py`)
오케스트레이션. 종목별 `try/except`로 한 종목 오류가 배치를 중단시키지 않게 격리(원본 스펙 8.2). 유니버스 진입/탈락·신호 발생 종목 로깅.

---

## 5. 오류 처리 / 안정성
- fetch 실패: 재시도 3회 exponential backoff
- rate limit: 호출 간 스로틀 sleep
- 종목별 예외 격리: 개별 오류는 로깅 후 스킵, 배치 계속
- 텔레그램 전송 실패: 로깅(재시도 1회)

---

## 6. 테스트 (원본 스펙 8.4)
- `test_indicators.py`: true_range·ATR·rolling_high/low를 알려진 입력-출력으로 검증. ATR(20) 결과를 TradingView `ATR(20)`와 대조(오차 1% 이내). `high_55`/`low_20`의 "오늘 제외"를 명시 케이스로 고정.
- `test_signals.py`: 각 상태 분류 경계값 테스트.
- `test_trading_params.py`: unit_size floor 동작, `<1` → 매매불가, 손절/피라미딩 계산.

순수 함수라 외부 I/O 없이 단위 테스트 가능.

---

## 7. 기술 스택
- Python 3.11+
- pandas, numpy (지표 계산)
- pykrx (국내 데이터)
- requests (텔레그램 봇 API)
- pytest (테스트)
- 스케줄: 시스템 cron (VPS)

---

## 8. 향후 확장 (본 MVP 범위 외)
어댑터/순수함수 분리 덕에 다음이 저비용으로 추가된다:
- 크립토 자산군 → `data/upbit.py` fetcher + `universe/crypto.py` 추가
- 직전 돌파 결과 필터(5.2) → 이력 저장소 도입 시
- `--date` 과거 재생성 → 대상일 인자만 노출(계산 로직 이미 순수)
- 시스템 1 병행 → indicators/signals에 20/10 파라미터 추가
- 영속 저장(PG) → `storage/` 어댑터 추가
