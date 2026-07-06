# 터틀 스크리닝 (MVP)

국내 주식·ETF를 대상으로 하는 **터틀 트레이딩 시스템 2** (55일 돌파 진입 / 20일 저가 청산) 일일 스크리닝 도구입니다. 무상태(stateless) 배치 프로세스로 설계되어 VPS에서 daily cron으로 자동 실행 가능하며, Telegram 알림을 통해 스크리닝 결과를 전송합니다.

## 설치

**요구 사항:** Python 3.11+

### 1. 레포지토리 클론 및 가상 환경 설정

```bash
cd /path/to/turtle-trading
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 설정 파일 준비

```bash
# .env 파일 생성 — Telegram 봇 토큰 입력
cp .env.example .env
# .env 편집: TELEGRAM_BOT_TOKEN=your-bot-token-here
```

```bash
# config.yaml 편집 필요한 항목:
# - account.total_value: 계정 총자산 (원)
# - account.risk_pct: 1회 거래 위험 비율
# - filters_stocks.kospi_top_n, kosdaq_top_n: 종목 선정 범위 (시가총액 상위 N)
# - approaching_pct: 돌파값 근접도 기준 (0.98 = 98%)
# - telegram_chat_id: Telegram 채팅 ID (숫자, 따옴표로 감싸기)
```

## 실행

### 명령줄 인터페이스

```bash
# 기본 실행: 직전 거래일을 자동으로 감지하여 스크리닝하고 Telegram으로 전송
python -m turtle.main

# 특정 날짜 스크리닝 (과거 데이터 재계산)
python -m turtle.main --date 2026-07-03

# Telegram 전송 없이 stdout으로만 출력 (테스트/디버그용)
python -m turtle.main --no-send
```

### 출력 예시

스크리닝 결과는 다음 정보를 포함합니다:

- **Breakout Signals**: 55일 고가를 넘은 종목 (진입 신호)
- **Position Sizing**: 각 종목의 추천 거래 단위 (계정 규모, ATR 변동성 기반)
- **구성**: KOSPI/KOSDAQ 별 스크리닝 결과, ETF 포함 (설정 가능)

## 테스트

```bash
# 전체 테스트 실행
python -m pytest -v

# 특정 모듈 테스트
python -m pytest tests/test_indicators.py -v
```

## Cron 설정 (자동 실행)

### VPS 환경 (장마감 후 실행)

KRX 장마감은 한국 시간 기준 15:30이므로, 일반적으로 16:10에 실행하도록 설정합니다.

```bash
# crontab 편집
crontab -e

# 다음 라인 추가 (매일 월~금 16:10 KST)
10 16 * * 1-5 cd /path/to/turtle-trading && /path/to/.venv/bin/python -m turtle.main >> run.log 2>&1
```

### 로그 모니터링

```bash
# 실시간 로그 확인
tail -f run.log

# 최근 실행 결과 확인
tail -20 run.log
```

## 한계 및 주의사항

### pykrx 엔드포인트 제약 (현재 개발 환경)

본 프로젝트는 pykrx를 통해 KRX 원본 API에 접근하려고 했으나, 다음의 KRX 엔드포인트들이 세션 인증(쿠키) 없이는 응답하지 않는 문제가 있습니다:

- **거래일 조회**: `pykrx.stock.get_previous_business_days()` 대신, 삼성전자(005930)의 OHLCV 데이터 인덱스를 거래일 소스로 사용합니다. (삼성전자는 KRX 최유동 종목으로 거래정지 리스크가 실질적으로 없어 안정적입니다.)
  
- **시가총액 순위**: `pykrx.stock.get_market_cap()` 대신, Naver Finance의 공개 시가총액 순위 페이지(`finance.naver.com`)를 크롤링합니다.

- **ETF 티커 목록**: `pykrx.stock.get_etf_ticker_list()` 대신, Naver Finance의 공개 JSON API(`finance.naver.com/api/sise/etfItemList.naver`)를 사용합니다.

**참고**: OHLCV 데이터 자체(가격, 거래량)는 pykrx의 `stock.get_market_ohlcv()` 함수를 통해 정상 조회되며, 이는 내부적으로 Naver Finance를 경유하므로 안정적입니다. 모든 지표 계산(55일 고가, 20일 저가, ATR, ADX 등)은 이 OHLCV 데이터를 기반으로 합니다.

> **운영 고려사항**: pykrx의 기반이 되는 KRX 공식 API는 KRX가 인터페이스를 변경할 때 불안정해질 수 있습니다. 실제 배포 환경(VPS 등)에서 이 문제가 여전히 존재하는지 확인 후, 필요시 더 견고한 데이터 소스(예: 증권사 OpenAPI)로의 전환을 검토하세요.

### MVP 제외 항목

- **관리종목/투자경고 필터**: pykrx 표준 API에서 제공하지 않아 미적용 (로깅으로 대체)
- **최근 액면분할 필터**: pykrx에서 제공하지 않아 미적용 (보수적으로 모든 종목 포함)
- **암호화폐**: 본 프로젝트는 KRX 현물시장만 대상 (설정에서 `crypto: false`로 고정)
- **이전 돌파 결과 필터**: 무상태 설계로 인해 미보유 (매일 신규 신호만 계산)
- **시스템 1 병행**: 순수 시스템 2만 구현
- **히스토리컬 백테스팅**: 설계 범위 밖 (과거 재현성은 `--date` 플래그로 제공)
- **데이터 영속성**: 무상태 배치로 데이터베이스 없음

