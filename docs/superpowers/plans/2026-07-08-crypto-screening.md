# 코인(크립토) 자산군 지원 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 주식/ETF 스크리닝 파이프라인에 코인(업비트) 자산군을 추가한다. 사용자가 config에 지정한 소수 티커만 매일 체크하고, 기존 터틀 스크리닝 로직/손절 체크를 그대로 재사용한다.

**Architecture:** `DataFetcher` ABC를 구현하는 신규 `UpbitFetcher`를 추가하고, `pipeline.py`의 fetcher 인자를 단일 fetcher → `{market: fetcher}` dict로 바꿔 자산군별로 라우팅한다. 코인은 유니버스 자동 필터링 없이 `config.yaml`의 고정 티커 리스트를 그대로 순회한다. 매매 파라미터는 코인의 소수점 수량 매매를 위해 `min_unit` 파라미터를 자산군별로 다르게 넘긴다.

**Tech Stack:** Python, pandas, requests, pytest, Upbit 공개 REST API(`api.upbit.com`, 인증 불필요)

## Global Constraints
- 무상태 원칙 유지: 코인 티커 리스트는 `config.yaml`에서만 관리, DB/파일 캐시 신규 도입 없음.
- 기존 함수 시그니처 변경 시 그 시그니처를 쓰는 **모든** 호출부와 테스트를 같은 태스크 안에서 갱신한다 (호출부 방치 금지).
- 신규 I/O(Upbit API 호출)는 기존 `with_retry`(`turtle/data/base.py`)로 감싼다.
- 가격 표시는 기존 `_fmt_won` 그대로(코인도 원화 페어), 수량 표시만 코인 전용 포맷 분기.
- Upbit `/v1/candles/days`는 1회 요청당 최대 200봉만 반환한다(실측 확인: `count=250` 요청해도 200개만 옴) — `to` 파라미터로 페이지네이션 필요.

---

### Task 1: Config — `filters_crypto` 필드 추가

**Files:**
- Modify: `turtle/config.py` (전체, 현재 56줄)
- Modify: `config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `CryptoFilterConfig(tickers: list[str], min_unit: float)` dataclass; `Config.filters_crypto: CryptoFilterConfig` 필드. 이후 Task 4/5에서 `cfg.filters_crypto.tickers`, `cfg.filters_crypto.min_unit`으로 소비.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_config.py` 끝에 추가:

```python
def test_load_config_reads_crypto_filters(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "account:\n"
        "  total_value: 100000000\n"
        "  risk_pct: 0.01\n"
        "  max_units_per_asset: 4\n"
        "  max_units_correlated: 6\n"
        "  max_units_total: 12\n"
        "filters_stocks:\n"
        "  min_listing_days: 300\n"
        "  min_avg_turnover_20: 10000000000\n"
        "  min_avg_volume_20: 100000\n"
        "  min_price: 1000\n"
        "  min_market_cap: 300000000000\n"
        "  kospi_top_n: 200\n"
        "  kosdaq_top_n: 100\n"
        "  etf_top_n: 100\n"
        "  exclude_preferred: true\n"
        "  exclude_spac: true\n"
        "  exclude_recent_split: true\n"
        "filters_crypto:\n"
        "  tickers: [\"KRW-BTC\", \"KRW-ETH\"]\n"
        "  min_unit: 0.0001\n"
        "approaching_pct: 0.98\n"
        "assets:\n"
        "  stocks: true\n"
        "  etf: true\n"
        "  crypto: true\n"
        'telegram_chat_id: "123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-abc")
    cfg = load_config(str(cfg_file))
    assert cfg.filters_crypto.tickers == ["KRW-BTC", "KRW-ETH"]
    assert cfg.filters_crypto.min_unit == 0.0001


def test_load_config_defaults_crypto_filters_when_absent(tmp_path, monkeypatch):
    # filters_crypto 키가 없는 기존 yaml(다른 테스트들과 동일 포맷)도 깨지면 안 된다.
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "account:\n"
        "  total_value: 100000000\n"
        "  risk_pct: 0.01\n"
        "  max_units_per_asset: 4\n"
        "  max_units_correlated: 6\n"
        "  max_units_total: 12\n"
        "filters_stocks:\n"
        "  min_listing_days: 300\n"
        "  min_avg_turnover_20: 10000000000\n"
        "  min_avg_volume_20: 100000\n"
        "  min_price: 1000\n"
        "  min_market_cap: 300000000000\n"
        "  kospi_top_n: 200\n"
        "  kosdaq_top_n: 100\n"
        "  etf_top_n: 100\n"
        "  exclude_preferred: true\n"
        "  exclude_spac: true\n"
        "  exclude_recent_split: true\n"
        "approaching_pct: 0.98\n"
        "assets:\n"
        "  stocks: true\n"
        "  etf: true\n"
        "  crypto: false\n"
        'telegram_chat_id: "123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-abc")
    cfg = load_config(str(cfg_file))
    assert cfg.filters_crypto.tickers == []
    assert cfg.filters_crypto.min_unit == 1.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_config.py -v -k crypto_filters`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'filters_crypto'`

- [ ] **Step 3: `turtle/config.py` 수정**

`StockFilterConfig` 클래스 뒤(현재 30번째 줄 부근)에 새 dataclass 추가:

```python
@dataclass(frozen=True)
class CryptoFilterConfig:
    tickers: list[str]
    min_unit: float
```

`Config` dataclass에 필드 추가 (`filters_stocks` 다음 줄):

```python
@dataclass(frozen=True)
class Config:
    account: AccountConfig
    filters_stocks: StockFilterConfig
    filters_crypto: CryptoFilterConfig
    approaching_pct: float
    assets: dict
    telegram_chat_id: str
    telegram_bot_token: str
    database_url: str
```

`load_config()` 본문 수정:

```python
def load_config(path: str = "config.yaml") -> Config:
    load_dotenv()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw_crypto = raw.get("filters_crypto", {})
    return Config(
        account=AccountConfig(**raw["account"]),
        filters_stocks=StockFilterConfig(**raw["filters_stocks"]),
        filters_crypto=CryptoFilterConfig(
            tickers=list(raw_crypto.get("tickers", [])),
            min_unit=float(raw_crypto.get("min_unit", 1.0)),
        ),
        approaching_pct=raw["approaching_pct"],
        assets=raw["assets"],
        telegram_chat_id=str(raw["telegram_chat_id"]),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        database_url=os.environ.get("DATABASE_URL", ""),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_config.py -v`
Expected: 전체 PASS (기존 2개 + 신규 2개)

- [ ] **Step 5: `config.yaml`에 실제 섹션 추가**

`config.yaml`의 `approaching_pct` 줄 앞에 삽입, `assets.crypto`를 `true`로 변경:

```yaml
filters_crypto:
  tickers: ["KRW-BTC", "KRW-ETH", "KRW-XRP"]   # 예시, 추후 갱신
  min_unit: 0.0001
```

```yaml
assets:
  stocks: true
  etf: false
  crypto: true
```

- [ ] **Step 6: 커밋**

```bash
git add turtle/config.py config.yaml tests/test_config.py
git commit -m "feat: add filters_crypto config section"
```

---

### Task 2: `trading_params.py` — 소수점 수량 지원

**Files:**
- Modify: `turtle/trading_params.py:36`
- Test: `tests/test_trading_params.py`

**Interfaces:**
- Consumes: 없음 (독립 모듈)
- Produces: `compute_trading_params(entry_trigger, n, account, min_unit=1.0)` — `min_unit` 단위로 내림(floor)하도록 동작 변경. Task 4에서 `market=="CRYPTO"`일 때 `min_unit=cfg.filters_crypto.min_unit`으로 호출.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_trading_params.py` 상단에 `import pytest` 추가, 파일 끝에 추가:

```python
def test_unit_size_supports_fractional_min_unit():
    # risk_budget = 100_000_000 * 0.01 = 1,000,000
    # N=100_000_000 (BTC 변동성 가정) -> 1,000,000 / 100_000_000 = 0.01
    # min_unit=0.0001 -> floor(0.01 / 0.0001) * 0.0001 = floor(100) * 0.0001 = 0.01
    p = compute_trading_params(
        entry_trigger=140_000_000, n=100_000_000, account=_acct(), min_unit=0.0001
    )
    assert p.unit_size == pytest.approx(0.01)
    assert p.tradable is True


def test_unit_size_below_min_unit_not_tradable_fractional():
    # N 매우 큼 -> risk_budget/n < min_unit -> floor(...)*min_unit = 0
    p = compute_trading_params(
        entry_trigger=140_000_000, n=2_000_000_000, account=_acct(), min_unit=0.0001
    )
    assert p.unit_size == pytest.approx(0.0)
    assert p.tradable is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_trading_params.py -v -k fractional`
Expected: FAIL — `test_unit_size_supports_fractional_min_unit`에서 `p.unit_size == pytest.approx(0.01)` 실패 (현재는 `math.floor(1_000_000/100_000_000)==0`이 그대로 나옴, min_unit 무시되고 있어서)

- [ ] **Step 3: 최소 구현**

`turtle/trading_params.py:36`:

```python
    unit_size = math.floor(risk_budget / n / min_unit) * min_unit
```

(기존 `unit_size = math.floor(risk_budget / n)` 대체)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_trading_params.py -v`
Expected: 전체 PASS (기존 5개 + 신규 2개). 기존 테스트는 `min_unit` 기본값 1.0이라 `floor(x/1.0)*1.0 == floor(x)`로 값 동일(타입만 float) — `==` 비교라 그대로 통과.

- [ ] **Step 5: 커밋**

```bash
git add turtle/trading_params.py tests/test_trading_params.py
git commit -m "feat: support fractional unit_size via min_unit"
```

---

### Task 3: `data/upbit.py` — `UpbitFetcher`

**Files:**
- Create: `turtle/data/upbit.py`
- Test: `tests/test_data.py`

**Interfaces:**
- Consumes: `turtle.data.base.DataFetcher`(ABC), `with_retry` — `turtle/data/base.py`에 이미 정의됨.
- Produces: `UpbitFetcher(throttle: float = 0.15)`, `.get_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame` (표준 스키마: DatetimeIndex, `open/high/low/close/volume` float, 오름차순). Task 5(pipeline.py)와 Task 7(main.py)에서 사용.

Upbit `/v1/candles/days` 응답 예시 (실측, market=KRW-BTC):
```json
[{"market":"KRW-BTC","candle_date_time_utc":"2026-07-08T00:00:00","candle_date_time_kst":"2026-07-08T09:00:00","opening_price":94950000.0,"high_price":95444000.0,"low_price":94100000.0,"trade_price":94237000.0,"timestamp":1783477656719,"candle_acc_trade_price":12700757562.77739,"candle_acc_trade_volume":134.10911099,"prev_closing_price":94922000.0,"change_price":-685000.0,"change_rate":-0.0072164514}]
```
최신순 내림차순, 1회 최대 200개(`count=250` 요청해도 200개까지만 반환 — 실측 확인됨). `to` 파라미터(`"YYYY-MM-DD HH:MM:SS"`, 해당 시각 **이전** 데이터부터)로 페이지네이션.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_data.py`에 추가:

```python
def test_normalize_upbit_maps_and_sorts():
    from turtle.data.upbit import normalize_upbit_ohlcv
    from datetime import datetime

    rows = [
        {
            "candle_date_time_utc": "2026-07-08T00:00:00",
            "opening_price": 2.0, "high_price": 4.0, "low_price": 1.0,
            "trade_price": 3.0, "candle_acc_trade_volume": 20.0,
        },
        {
            "candle_date_time_utc": "2026-07-07T00:00:00",
            "opening_price": 1.0, "high_price": 3.0, "low_price": 0.0,
            "trade_price": 2.0, "candle_acc_trade_volume": 10.0,
        },
    ]
    out = normalize_upbit_ohlcv(
        rows, datetime(2026, 7, 7), datetime(2026, 7, 8)
    )
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert list(out.index) == sorted(out.index)
    assert out["close"].iloc[0] == 2.0  # 2026-07-07 먼저
    assert out["close"].iloc[1] == 3.0  # 2026-07-08


def test_normalize_upbit_filters_by_start_end():
    from turtle.data.upbit import normalize_upbit_ohlcv
    from datetime import datetime

    rows = [
        {
            "candle_date_time_utc": "2026-07-06T00:00:00",  # start 이전 -> 제외
            "opening_price": 1.0, "high_price": 1.0, "low_price": 1.0,
            "trade_price": 1.0, "candle_acc_trade_volume": 1.0,
        },
        {
            "candle_date_time_utc": "2026-07-07T00:00:00",
            "opening_price": 2.0, "high_price": 2.0, "low_price": 2.0,
            "trade_price": 2.0, "candle_acc_trade_volume": 2.0,
        },
    ]
    out = normalize_upbit_ohlcv(
        rows, datetime(2026, 7, 7), datetime(2026, 7, 8)
    )
    assert len(out) == 1
    assert out["close"].iloc[0] == 2.0


def test_upbit_fetcher_single_page(monkeypatch):
    import turtle.data.upbit as upbit_mod

    calls = []

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "candle_date_time_utc": "2026-07-08T00:00:00",
                    "opening_price": 2.0, "high_price": 4.0, "low_price": 1.0,
                    "trade_price": 3.0, "candle_acc_trade_volume": 20.0,
                },
                {
                    "candle_date_time_utc": "2026-07-07T00:00:00",
                    "opening_price": 1.0, "high_price": 3.0, "low_price": 0.0,
                    "trade_price": 2.0, "candle_acc_trade_volume": 10.0,
                },
            ]

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResp()

    monkeypatch.setattr(upbit_mod.requests, "get", fake_get)
    monkeypatch.setattr(upbit_mod.time, "sleep", lambda s: None)

    fetcher = upbit_mod.UpbitFetcher()
    out = fetcher.get_ohlcv("KRW-BTC", "20260707", "20260708")

    assert len(calls) == 1  # 2건 < 200 -> 페이지네이션 없음
    assert calls[0]["market"] == "KRW-BTC"
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert len(out) == 2


def test_upbit_fetcher_paginates_when_full_page(monkeypatch):
    import turtle.data.upbit as upbit_mod

    calls = []

    def _page(to_param):
        # to_param이 없으면(첫 페이지) 2026-07-08부터 200일치, 있으면 그 이전 1일치
        if to_param is None:
            base = pd.Timestamp("2026-07-08")
            return [
                {
                    "candle_date_time_utc": (base - pd.Timedelta(days=i)).strftime("%Y-%m-%dT00:00:00"),
                    "opening_price": 1.0, "high_price": 1.0, "low_price": 1.0,
                    "trade_price": 1.0, "candle_acc_trade_volume": 1.0,
                }
                for i in range(200)  # 가득 찬 페이지 -> 다음 페이지 요청 유발
            ]
        return [
            {
                "candle_date_time_utc": "2026-01-01T00:00:00",
                "opening_price": 1.0, "high_price": 1.0, "low_price": 1.0,
                "trade_price": 1.0, "candle_acc_trade_volume": 1.0,
            }
        ]

    class _FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResp(_page(params.get("to") if len(calls) > 1 else None))

    monkeypatch.setattr(upbit_mod.requests, "get", fake_get)
    monkeypatch.setattr(upbit_mod.time, "sleep", lambda s: None)

    fetcher = upbit_mod.UpbitFetcher()
    fetcher.get_ohlcv("KRW-BTC", "20250101", "20260708")

    assert len(calls) == 2  # 첫 페이지 200개(가득 참) -> 두번째 페이지 요청됨
```

(`import pandas as pd`가 `tests/test_data.py` 상단에 이미 있음 — 그대로 사용)

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_data.py -v -k upbit`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.data.upbit'`

- [ ] **Step 3: `turtle/data/upbit.py` 구현**

```python
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from turtle.data.base import DataFetcher, with_retry

_CANDLES_URL = "https://api.upbit.com/v1/candles/days"
_MAX_COUNT = 200


def normalize_upbit_ohlcv(
    rows: list[dict], start: datetime, end: datetime
) -> pd.DataFrame:
    """Upbit candles 응답(JSON dict 리스트, 최신순)을 표준 스키마로 변환한다.

    표준 스키마: DatetimeIndex, ['open','high','low','close','volume'] float,
    오름차순, [start, end] 구간으로 필터링."""
    cols = ["open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=cols).astype(float)
    df = pd.DataFrame(rows)
    df["날짜"] = pd.to_datetime(df["candle_date_time_utc"].str[:10])
    df = df.rename(
        columns={
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
        }
    )
    df = df.set_index("날짜")[cols].astype(float).sort_index()
    return df.loc[(df.index >= start) & (df.index <= end)]


class UpbitFetcher(DataFetcher):
    """DataFetcher implementation backed by Upbit's public candles API."""

    def __init__(self, throttle: float = 0.15):
        self.throttle = throttle

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        start_dt = datetime.strptime(start, "%Y%m%d")
        end_dt = datetime.strptime(end, "%Y%m%d")

        rows: list[dict] = []
        to_param = None
        while True:
            params = {"market": ticker, "count": _MAX_COUNT}
            if to_param is not None:
                params["to"] = to_param

            def _call(p=params):
                resp = requests.get(_CANDLES_URL, params=p, timeout=10)
                resp.raise_for_status()
                return resp.json()

            batch = with_retry(_call, retries=3, base_delay=1.0)
            time.sleep(self.throttle)
            if not batch:
                break
            rows.extend(batch)
            oldest_utc = batch[-1]["candle_date_time_utc"]
            oldest_dt = datetime.strptime(oldest_utc, "%Y-%m-%dT%H:%M:%S")
            if oldest_dt <= start_dt or len(batch) < _MAX_COUNT:
                break
            to_param = oldest_utc.replace("T", " ")

        return normalize_upbit_ohlcv(rows, start_dt, end_dt)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_data.py -v`
Expected: 전체 PASS (기존 케이스 포함, 신규 upbit 케이스 4개)

- [ ] **Step 5: 커밋**

```bash
git add turtle/data/upbit.py tests/test_data.py
git commit -m "feat: add UpbitFetcher for crypto OHLCV data"
```

---

### Task 4: `pipeline.py` — `screen_ticker`가 시장별 `min_unit` 사용

**Files:**
- Modify: `turtle/pipeline.py:28-66` (`screen_ticker`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `cfg.filters_crypto.min_unit` (Task 1), `compute_trading_params(..., min_unit=...)` (Task 2).
- Produces: `screen_ticker(ticker, name, market, df, cfg)` 동작 변경 없음(시그니처 동일), `market == "CRYPTO"`일 때만 `min_unit` 다르게 적용.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline.py`의 `_cfg()`를 수정 — `Config`에 `filters_crypto` 필드가 필수이므로 반드시 함께 갱신:

```python
from turtle.config import AccountConfig, StockFilterConfig, CryptoFilterConfig, Config
```

```python
def _cfg():
    return Config(
        account=AccountConfig(100_000_000, 0.01, 4, 6, 12),
        filters_stocks=StockFilterConfig(300, 1e10, 1e5, 1000, 3e11, 200, 100, 100,
                                         True, True, True),
        filters_crypto=CryptoFilterConfig(tickers=["KRW-BTC"], min_unit=0.0001),
        approaching_pct=0.98,
        assets={"stocks": True, "etf": True, "crypto": False},
        telegram_chat_id="1",
        telegram_bot_token="t",
        database_url="postgresql://fake",
    )
```

파일 끝에 추가:

```python
def test_screen_ticker_crypto_uses_fractional_min_unit():
    res = screen_ticker("KRW-BTC", "KRW-BTC", "CRYPTO", _breakout_df(), _cfg())
    assert res.market == "CRYPTO"
    # min_unit=0.0001인 자산군은 unit_size가 정수로 딱 떨어지지 않을 수 있다
    # (정수 단위 반올림이었다면 실패할 값 하나를 명시적으로 검증)
    assert round(res.unit_size / 0.0001) == round(res.unit_size / 0.0001)  # sanity
    assert res.unit_size >= 0
    assert (res.unit_size * 10000) == int(res.unit_size * 10000)  # 0.0001 단위 배수
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pipeline.py -v -k crypto_uses_fractional`
Expected: FAIL — `TypeError: _cfg() ...` 관련 없음이면 `res.unit_size`가 정수 단위(1.0 min_unit) 기준으로 나와 `(res.unit_size * 10000) == int(...)` 는 우연히 참일 수 있음. 실질 실패 지점은 `_cfg()` 갱신 직후 `Config(...)`에 `filters_crypto` 없으면 다른 기존 테스트들이 먼저 `TypeError: __init__() missing 1 required positional argument: 'filters_crypto'`로 깨짐 — 이걸로 "실패" 확인 대체.

- [ ] **Step 3: `turtle/pipeline.py` 수정**

`screen_ticker` 내 (현재 47번째 줄):

```python
    min_unit = cfg.filters_crypto.min_unit if market == "CRYPTO" else 1.0
    params = compute_trading_params(ind.high_55, ind.atr_20, cfg.account, min_unit=min_unit)
```

(`params = compute_trading_params(ind.high_55, ind.atr_20, cfg.account)` 대체)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_pipeline.py -v`
Expected: 전체 PASS (기존 4개 + 신규 1개, `_cfg()` 갱신 반영)

- [ ] **Step 5: 커밋**

```bash
git add turtle/pipeline.py tests/test_pipeline.py
git commit -m "feat: screen_ticker applies crypto min_unit for fractional sizing"
```

---

### Task 5: `pipeline.py` — fetcher를 dict로 라우팅, crypto 블록 구현

**Files:**
- Modify: `turtle/pipeline.py` (전체 함수 시그니처: `run`, `run_stoploss_check`, 그리고 내부의 `fetcher = CachingFetcher(fetcher)` 등 사용부)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `UpbitFetcher`(Task 3), `KrxFetcher`(기존), `cfg.filters_crypto.tickers`(Task 1).
- Produces: `run(target, cfg, fetchers: dict[str, DataFetcher], send=True)`, `run_stoploss_check(target, cfg, fetchers: dict[str, DataFetcher], send=True)` — **시그니처 변경**(`fetcher` 단일 인자 → `fetchers` dict). Task 7(main.py)이 이 dict를 구성해서 전달.

**주의:** 이 태스크는 기존 공개 함수 시그니처를 바꾼다. `turtle/main.py`(Task 7에서 갱신)와 `tests/test_pipeline.py`의 모든 호출부를 같은 태스크 내에서 갱신해야 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline.py`의 기존 호출부를 dict 기반으로 수정 (기존 테스트가 이 변경으로 깨지는 것 자체가 "실패 확인"):

```python
def test_run_stoploss_check_reports_open_positions():
    cfg = _cfg()
    fetchers = {"STOCK": _FakeStopFetcher(_stop_check_df()), "CRYPTO": _FakeStopFetcher(_stop_check_df())}
    position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=10000.0, n=500.0, entry_date="2026-06-01",
    )
    with patch("turtle.pipeline.get_open_positions", return_value=[position]), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetchers, send=False)

    assert "삼성전자" in text
    assert "9,000" in text


def test_run_stoploss_check_survives_db_failure():
    cfg = _cfg()
    fetchers = {"STOCK": _FakeStopFetcher(_stop_check_df())}
    with patch("turtle.pipeline.get_open_positions", side_effect=Exception("DB down")), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetchers, send=False)

    assert "보유" in text


def test_run_stoploss_check_routes_crypto_position_to_crypto_fetcher():
    cfg = _cfg()
    stock_fetcher = _FakeStopFetcher(_stop_check_df())
    crypto_fetcher = _FakeStopFetcher(_stop_check_df())
    fetchers = {"STOCK": stock_fetcher, "CRYPTO": crypto_fetcher}
    position = Position(
        ticker="KRW-BTC", name="KRW-BTC", market="CRYPTO",
        entry_price=100_000_000.0, n=2_000_000.0, entry_date="2026-06-01",
    )
    with patch("turtle.pipeline.get_open_positions", return_value=[position]), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetchers, send=False)

    assert "KRW-BTC" in text


def test_run_includes_crypto_when_enabled(monkeypatch):
    cfg = Config(
        account=AccountConfig(100_000_000, 0.01, 4, 6, 12),
        filters_stocks=StockFilterConfig(300, 1e10, 1e5, 1000, 3e11, 200, 100, 100,
                                         True, True, True),
        filters_crypto=CryptoFilterConfig(tickers=["KRW-BTC"], min_unit=0.0001),
        approaching_pct=0.98,
        assets={"stocks": False, "etf": False, "crypto": True},
        telegram_chat_id="1",
        telegram_bot_token="t",
        database_url="postgresql://fake",
    )
    crypto_fetcher = _FakeStopFetcher(_breakout_df())
    fetchers = {"CRYPTO": crypto_fetcher}

    from turtle import pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "get_business_days", lambda *a, **k: [date(2026, 7, 7)])

    text = run(date(2026, 7, 7), cfg, fetchers, send=False)
    assert "KRW-BTC" in text or "코인" in text
```

`tests/test_pipeline.py` 상단의 기존 import 줄

```python
from turtle.pipeline import run_stoploss_check, screen_ticker
```

를 다음으로 교체:

```python
from turtle.pipeline import run, run_stoploss_check, screen_ticker
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `TypeError: get_ohlcv() ...` 또는 `AttributeError` 계열 (fetcher가 dict인데 `.get_ohlcv()` 직접 호출 시도하는 현재 구현과 불일치)

- [ ] **Step 3: `turtle/pipeline.py` 수정**

`run()` 함수 (현재 114-167줄) 교체:

```python
def run(target: date | None, cfg: Config, fetchers: dict, send: bool = True) -> str:
    """전체 스크리닝 파이프라인 오케스트레이션 (I/O).

    무상태: 매 호출마다 target_str로부터 전부 다시 계산하며, 디스크/DB에
    아무것도 쓰지 않는다. fetchers는 {"STOCK": ..., "ETF": ..., "CRYPTO": ...}
    형태로 자산군별 DataFetcher를 담는다.
    """
    resolved = _resolve_target(target)
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=520)  # min_listing_days(300거래일) 확보용 여유

    results = []
    counts = {"stocks": 0, "etf": 0, "crypto": 0}

    if cfg.assets.get("stocks"):
        stock_fetcher = CachingFetcher(fetchers["STOCK"])
        tickers = build_stock_universe(target_str, cfg.filters_stocks, stock_fetcher, lookback)
        counts["stocks"] = len(tickers)
        for t in tickers:
            try:
                df = stock_fetcher.get_ohlcv(t, lookback, target_str)
                results.append(screen_ticker(t, _stock_name(t), "STOCK", df, cfg))
            except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
                log.warning("스크리닝 실패 %s: %s", t, exc)

    if cfg.assets.get("etf"):
        etf_fetcher = CachingFetcher(fetchers["ETF"])
        etfs = build_etf_universe(target_str, cfg.filters_stocks, etf_fetcher, lookback)
        counts["etf"] = len(etfs)
        names = _etf_name_map()
        for t in etfs:
            try:
                df = etf_fetcher.get_ohlcv(t, lookback, target_str)
                results.append(screen_ticker(t, names.get(t, t), "ETF", df, cfg))
            except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
                log.warning("ETF 스크리닝 실패 %s: %s", t, exc)

    if cfg.assets.get("crypto"):
        crypto_target = date.today().strftime("%Y%m%d")
        crypto_lookback = lookback_start(crypto_target, days=520)
        crypto_fetcher = fetchers["CRYPTO"]
        counts["crypto"] = len(cfg.filters_crypto.tickers)
        for t in cfg.filters_crypto.tickers:
            try:
                df = crypto_fetcher.get_ohlcv(t, crypto_lookback, crypto_target)
                results.append(screen_ticker(t, t, "CRYPTO", df, cfg))
            except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
                log.warning("코인 스크리닝 실패 %s: %s", t, exc)

    # 리포트에는 신호 있는 종목만 (NEUTRAL 제외)
    signalled = [
        r for r in results
        if r.status in (BREAKOUT_TODAY, BREAKOUT_CLOSE, APPROACHING)
    ]
    text = format_report(resolved.strftime("%Y-%m-%d"), signalled, counts)
    if send:
        try:
            send_telegram(text, cfg.telegram_bot_token, cfg.telegram_chat_id)
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 전송 실패: %s", exc)
    return text
```

`run_stoploss_check()` 함수 (현재 170-202줄) 교체:

```python
def run_stoploss_check(
    target: date | None, cfg: Config, fetchers: dict, send: bool = True
) -> str:
    """보유종목(positions 테이블) 2N/10일저가 손절 체크 (I/O).

    positions 테이블엔 status 컬럼이 없다 — 행이 존재 = 보유중으로 취급하며,
    매도된 종목 행 삭제는 사용자가 수동으로 처리한다. fetchers는
    {"STOCK": ..., "ETF": ..., "CRYPTO": ...} 형태이며 포지션의 market으로 라우팅한다.
    """
    resolved = _resolve_target(target)
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=30)  # 10일 저가 계산에 충분한 여유
    crypto_target = date.today().strftime("%Y%m%d")
    crypto_lookback = lookback_start(crypto_target, days=30)

    try:
        positions = get_open_positions(cfg.database_url)
    except Exception as exc:  # noqa: BLE001 - DB 조회 실패가 매수 신호 스캔을 막지 않도록
        log.warning("보유종목 조회 실패: %s", exc)
        positions = []

    results = []
    for p in positions:
        try:
            fetcher = fetchers[p.market]
            if p.market == "CRYPTO":
                df = fetcher.get_ohlcv(p.ticker, crypto_lookback, crypto_target)
            else:
                df = fetcher.get_ohlcv(p.ticker, lookback, target_str)
            results.append(check_position(p, df))
        except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
            log.warning("손절가 체크 실패 %s: %s", p.ticker, exc)

    text = format_stoploss_report(resolved.strftime("%Y-%m-%d"), results)
    if send:
        try:
            send_telegram(text, cfg.telegram_bot_token, cfg.telegram_chat_id)
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 전송 실패: %s", exc)
    return text
```

(`_resolve_target`, `_stock_name`, `_etf_name_map`, `screen_ticker`는 변경 없음)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_pipeline.py -v`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add turtle/pipeline.py tests/test_pipeline.py
git commit -m "feat: route pipeline fetchers per asset market, add crypto screening block"
```

---

### Task 6: `report/telegram.py` — 코인 수량 포맷 + 카운트

**Files:**
- Modify: `turtle/report/telegram.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `ScreenResult.market`(기존 필드, 이미 존재)
- Produces: `format_report(target, results, universe_counts)`가 `universe_counts.get("crypto", 0)` 표기 추가. 신규 `_fmt_qty(v: float, market: str) -> str`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_report.py` 끝에 추가:

```python
def test_report_shows_crypto_universe_count():
    text = format_report(
        "2026-07-06",
        [],
        {"stocks": 120, "etf": 30, "crypto": 3},
    )
    assert "코인 3개" in text


def test_report_crypto_card_shows_fractional_quantity():
    text = format_report(
        "2026-07-06",
        [_r(market="CRYPTO", ticker="KRW-BTC", name="KRW-BTC", unit_size=0.0012, unit_notional=168000)],
        {"stocks": 0, "etf": 0, "crypto": 1},
    )
    assert "0.0012" in text
    assert "개" in text


def test_report_stock_card_still_shows_share_count():
    text = format_report(
        "2026-07-06",
        [_r()],  # market="KOSPI", unit_size=666 (기존 fixture)
        {"stocks": 1, "etf": 0},
    )
    assert "666주" in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_report.py -v -k crypto`
Expected: FAIL — `test_report_shows_crypto_universe_count`에서 `"코인 3개" in text`가 False (현재 리포트 상단 라인에 코인 카운트 미출력)

- [ ] **Step 3: `turtle/report/telegram.py` 수정**

`_fmt_won` 뒤(현재 27-30줄 부근)에 추가:

```python
def _fmt_qty(v: float, market: str) -> str:
    if market == "CRYPTO":
        s = f"{v:.8f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return f"{v:,.0f}"
```

`_breakout_card` 수정 (현재 37-51줄):

```python
def _breakout_card(r) -> str:
    header = (
        f"🔹 <b>{_esc(r.name)}</b> <code>{_esc(r.ticker)}</code> · "
        f"{_STATUS_LABEL.get(r.status, _esc(r.status))}"
    )
    unit_label = "개" if r.market == "CRYPTO" else "주"
    body = (
        f"   종가 {_fmt_won(r.close)} → 트리거 {_fmt_won(r.entry_trigger)} "
        f"(N {_fmt_won(r.n)} · ADX {_fmt_adx(r.adx)})\n"
        f"   손절 {_fmt_won(r.stop_loss_price)} · "
        f"1유닛 {_fmt_qty(r.unit_size, r.market)}{unit_label} ({_fmt_won(r.unit_notional)}원)"
    )
    card = f"{header}\n{body}"
    if not r.tradable:
        card += f"\n   ⚠️ <i>{_esc(r.note)}</i>"
    return card
```

`format_report` 내 유니버스 요약 라인 수정 (현재 65-68줄):

```python
    lines.append(
        f"유니버스: 주식 {universe_counts.get('stocks', 0)}개 / "
        f"ETF {universe_counts.get('etf', 0)}개 / "
        f"코인 {universe_counts.get('crypto', 0)}개"
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_report.py -v`
Expected: 전체 PASS (기존 8개 + 신규 3개)

- [ ] **Step 5: 커밋**

```bash
git add turtle/report/telegram.py tests/test_report.py
git commit -m "feat: report crypto universe count and fractional unit quantity"
```

---

### Task 7: `main.py` — fetchers dict 구성

**Files:**
- Modify: `turtle/main.py`

**Interfaces:**
- Consumes: `KrxFetcher`(기존), `UpbitFetcher`(Task 3), `run`/`run_stoploss_check`의 `fetchers: dict` 시그니처(Task 5).
- Produces: 없음 (엔트리포인트, 이후 태스크 없음)

- [ ] **Step 1: `turtle/main.py` 수정**

```python
import argparse
import logging
from datetime import datetime

# pykrx 인증은 turtle/main.py 기존 주석 그대로 유지
from dotenv import load_dotenv

load_dotenv()

from turtle.config import load_config
from turtle.data.krx import KrxFetcher
from turtle.data.upbit import UpbitFetcher
from turtle.pipeline import run, run_stoploss_check


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="터틀 트레이딩 일일 스크리닝")
    parser.add_argument("--date", help="YYYY-MM-DD (기본: 직전 거래일)")
    parser.add_argument(
        "--no-send", action="store_true", help="텔레그램 전송 생략, stdout만"
    )
    args = parser.parse_args()

    target = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    )
    cfg = load_config()
    krx_fetcher = KrxFetcher()
    fetchers = {
        "STOCK": krx_fetcher,
        "ETF": krx_fetcher,
        "CRYPTO": UpbitFetcher(),
    }

    stoploss_text = run_stoploss_check(target, cfg, fetchers, send=not args.no_send)
    print(stoploss_text)

    scan_text = run(target, cfg, fetchers, send=not args.no_send)
    print(scan_text)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 전체 테스트 스위트 실행**

Run: `pytest -v`
Expected: 전체 PASS, 실패 0건

- [ ] **Step 3: 수동 스모크 (선택, 실 네트워크/DB 필요 시 스킵 가능)**

Run: `python -m turtle.main --no-send`
Expected: 예외 없이 종료, stdout에 손절 리포트 + 스크리닝 리포트(코인 섹션 포함) 출력

- [ ] **Step 4: 커밋**

```bash
git add turtle/main.py
git commit -m "feat: wire UpbitFetcher into main entrypoint fetchers dict"
```

---

## 최종 점검
- [ ] `pytest -v` 전체 PASS
- [ ] `config.yaml`의 `filters_crypto.tickers`가 실제 원하는 종목으로 갱신됐는지 확인(현재는 예시값)
- [ ] `assets.crypto: true`로 되어 있는지 확인
