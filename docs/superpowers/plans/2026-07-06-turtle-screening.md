# 터틀 스크리닝 시스템 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 국내주식·ETF를 매일 스크리닝해 터틀 시스템2(55일 돌파/20일 청산) 신호와 매매 파라미터를 계산하고 텔레그램으로 전송하는 무상태 배치.

**Architecture:** 순수 함수 코어(지표/신호/매매파라미터)를 I/O에서 분리하고, 데이터 수집은 `DataFetcher` 어댑터로 추상화한다. 각 실행은 대상일 하나에 대해 독립 완결되며 디스크·DB를 쓰지 않는다.

**Tech Stack:** Python 3.11+, pandas, numpy, pykrx, requests, pytest.

## Global Constraints

- Python 3.11+ 사용.
- 비밀값(텔레그램 봇 토큰)은 `.env`에서만 로드. 코드·yaml 하드코딩 금지.
- `high_55`/`low_20`는 **반드시 오늘(t) 캔들 제외** — `[t-55:t-1]`, `[t-20:t-1]`.
- ATR(=N)은 Wilder 방식. 첫 20일은 TR의 단순평균(SMA)으로 시드, 21일차부터 `N=(19·N_prev+TR)/20`.
- `unit_size`는 항상 **floor(내림)**. 반올림 금지.
- 데이터 수집 실패 시 재시도 3회 exponential backoff. 종목별 예외 격리(한 종목 오류가 배치 중단 금지).
- 모든 임계값·계좌값은 `config.yaml`에서 로드.
- OHLCV 표준 스키마: `pandas.DataFrame`, `DatetimeIndex`, 컬럼 `['open','high','low','close','volume']` (float).

---

### Task 1: 프로젝트 스캐폴드 + config 로더

**Files:**
- Create: `requirements.txt`
- Create: `config.yaml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `turtle/__init__.py`
- Create: `turtle/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `load_config(path: str = "config.yaml") -> Config`
  - `Config` dataclass 필드: `account: AccountConfig`, `filters_stocks: StockFilterConfig`, `approaching_pct: float`, `assets: dict[str, bool]`, `telegram_chat_id: str`, `telegram_bot_token: str`
  - `AccountConfig(total_value: float, risk_pct: float, max_units_per_asset: int, max_units_correlated: int, max_units_total: int)`
  - `StockFilterConfig(min_listing_days: int, min_avg_turnover_20: float, min_avg_volume_20: float, min_price: float, min_market_cap: float, kospi_top_n: int, kosdaq_top_n: int, exclude_preferred: bool, exclude_spac: bool, exclude_recent_split: bool)`

- [ ] **Step 1: requirements.txt 작성**

```
pandas>=2.0
numpy>=1.24
pykrx>=1.0.45
requests>=2.31
python-dotenv>=1.0
pytest>=8.0
```

- [ ] **Step 2: .gitignore 작성**

```
__pycache__/
*.pyc
.env
.venv/
.pytest_cache/
```

- [ ] **Step 3: .env.example 작성**

```
TELEGRAM_BOT_TOKEN=your-bot-token-here
```

- [ ] **Step 4: config.yaml 작성**

```yaml
account:
  total_value: 100000000
  risk_pct: 0.01
  max_units_per_asset: 4
  max_units_correlated: 6
  max_units_total: 12

filters_stocks:
  min_listing_days: 300
  min_avg_turnover_20: 10000000000
  min_avg_volume_20: 100000
  min_price: 1000
  min_market_cap: 300000000000
  kospi_top_n: 200
  kosdaq_top_n: 100
  exclude_preferred: true
  exclude_spac: true
  exclude_recent_split: true

approaching_pct: 0.98

assets:
  stocks: true
  etf: true
  crypto: false

telegram_chat_id: "YOUR_CHAT_ID"
```

- [ ] **Step 5: 실패하는 테스트 작성** (`tests/test_config.py`)

```python
from turtle.config import load_config, Config

def test_load_config_reads_yaml_and_env(tmp_path, monkeypatch):
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
    assert isinstance(cfg, Config)
    assert cfg.account.total_value == 100000000
    assert cfg.account.risk_pct == 0.01
    assert cfg.filters_stocks.min_listing_days == 300
    assert cfg.approaching_pct == 0.98
    assert cfg.assets["crypto"] is False
    assert cfg.telegram_chat_id == "123"
    assert cfg.telegram_bot_token == "tok-abc"
```

- [ ] **Step 6: 테스트 실패 확인**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.config'`

- [ ] **Step 7: 최소 구현** (`turtle/__init__.py` 빈 파일, `turtle/config.py`)

```python
import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class AccountConfig:
    total_value: float
    risk_pct: float
    max_units_per_asset: int
    max_units_correlated: int
    max_units_total: int


@dataclass(frozen=True)
class StockFilterConfig:
    min_listing_days: int
    min_avg_turnover_20: float
    min_avg_volume_20: float
    min_price: float
    min_market_cap: float
    kospi_top_n: int
    kosdaq_top_n: int
    exclude_preferred: bool
    exclude_spac: bool
    exclude_recent_split: bool


@dataclass(frozen=True)
class Config:
    account: AccountConfig
    filters_stocks: StockFilterConfig
    approaching_pct: float
    assets: dict
    telegram_chat_id: str
    telegram_bot_token: str


def load_config(path: str = "config.yaml") -> Config:
    load_dotenv()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(
        account=AccountConfig(**raw["account"]),
        filters_stocks=StockFilterConfig(**raw["filters_stocks"]),
        approaching_pct=raw["approaching_pct"],
        assets=raw["assets"],
        telegram_chat_id=str(raw["telegram_chat_id"]),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    )
```

`requirements.txt`에 `pyyaml>=6.0` 추가 (yaml import 위해).

- [ ] **Step 8: 테스트 통과 확인**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 9: 커밋**

```bash
git add requirements.txt config.yaml .env.example .gitignore turtle/__init__.py turtle/config.py tests/test_config.py
git commit -m "feat: project scaffold and config loader"
```

---

### Task 2: 지표 계산 (순수 함수)

**Files:**
- Create: `turtle/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Consumes: 표준 OHLCV `DataFrame` (Global Constraints 스키마)
- Produces:
  - `true_range(df: pd.DataFrame) -> pd.Series`
  - `atr_wilder(tr: pd.Series, period: int = 20) -> pd.Series`
  - `rolling_high(high: pd.Series, window: int) -> pd.Series` — 오늘 제외
  - `rolling_low(low: pd.Series, window: int) -> pd.Series` — 오늘 제외
  - `adx(df: pd.DataFrame, period: int = 14) -> pd.Series`
  - `IndicatorResult` dataclass: `close, high_55, low_20, high_20, low_10, tr, atr_20, adx_14, avg_volume_20, avg_turnover_20` (모두 float)
  - `compute_indicators(df: pd.DataFrame) -> IndicatorResult` — 마지막 행(오늘) 기준 값 산출

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_indicators.py`)

```python
import numpy as np
import pandas as pd
import pytest

from turtle.indicators import (
    true_range,
    atr_wilder,
    rolling_high,
    rolling_low,
    compute_indicators,
)


def _df(highs, lows, closes, vols=None):
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols if vols is not None else [1000] * n,
        },
        index=idx,
    )


def test_true_range_single_row():
    df = _df(highs=[100, 110], lows=[95, 90], closes=[100, 105])
    tr = true_range(df)
    # 둘째 행: max(110-90=20, |110-100|=10, |90-100|=10) = 20
    assert tr.iloc[1] == 20


def test_atr_wilder_constant_tr_is_constant():
    tr = pd.Series([2.0] * 25)
    atr = atr_wilder(tr, period=20)
    assert atr.iloc[-1] == pytest.approx(2.0)


def test_atr_wilder_seed_is_sma_then_wilder():
    tr = pd.Series([float(i) for i in range(1, 21)] + [21.0])  # 1..20, then 21
    atr = atr_wilder(tr, period=20)
    # seed(20번째) = mean(1..20) = 10.5
    assert atr.iloc[19] == pytest.approx(10.5)
    # 21번째 = (19*10.5 + 21)/20 = 11.025
    assert atr.iloc[20] == pytest.approx(11.025)


def test_rolling_high_excludes_today():
    high = pd.Series([1, 2, 3, 4, 5], dtype=float)
    rh = rolling_high(high, window=3)
    # 마지막 원소(5) 기준 직전 3봉 [2,3,4]의 max = 4 (오늘 5 제외)
    assert rh.iloc[-1] == 4


def test_rolling_low_excludes_today():
    low = pd.Series([5, 4, 3, 2, 1], dtype=float)
    rl = rolling_low(low, window=3)
    # 마지막 원소(1) 기준 직전 3봉 [4,3,2]의 min = 2 (오늘 1 제외)
    assert rl.iloc[-1] == 2


def test_compute_indicators_returns_latest_values():
    n = 80
    highs = list(np.linspace(100, 180, n))
    lows = [h - 5 for h in highs]
    closes = [h - 2 for h in highs]
    df = _df(highs, lows, closes)
    res = compute_indicators(df)
    assert res.close == pytest.approx(closes[-1])
    # high_55: 직전 55봉(오늘 제외) 최고가
    assert res.high_55 == pytest.approx(max(highs[-56:-1]))
    assert res.low_20 == pytest.approx(min(lows[-21:-1]))
    assert res.atr_20 > 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_indicators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.indicators'`

- [ ] **Step 3: 최소 구현** (`turtle/indicators.py`)

```python
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IndicatorResult:
    close: float
    high_55: float
    low_20: float
    high_20: float
    low_10: float
    tr: float
    atr_20: float
    adx_14: float
    avg_volume_20: float
    avg_turnover_20: float


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    hl = df["high"] - df["low"]
    hc = (df["high"] - prev_close).abs()
    lc = (df["low"] - prev_close).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr_wilder(tr: pd.Series, period: int = 20) -> pd.Series:
    tr = tr.reset_index(drop=True)
    atr = pd.Series(np.nan, index=tr.index, dtype=float)
    if len(tr) < period:
        return atr
    seed = tr.iloc[:period].mean()
    atr.iloc[period - 1] = seed
    prev = seed
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr.iloc[i]) / period
        atr.iloc[i] = prev
    return atr


def rolling_high(high: pd.Series, window: int) -> pd.Series:
    return high.shift(1).rolling(window).max()


def rolling_low(low: pd.Series, window: int) -> pd.Series:
    return low.shift(1).rolling(window).min()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> IndicatorResult:
    df = df.sort_index()
    tr = true_range(df)
    atr = atr_wilder(tr, period=20)
    turnover = df["close"] * df["volume"]
    return IndicatorResult(
        close=float(df["close"].iloc[-1]),
        high_55=float(rolling_high(df["high"], 55).iloc[-1]),
        low_20=float(rolling_low(df["low"], 20).iloc[-1]),
        high_20=float(rolling_high(df["high"], 20).iloc[-1]),
        low_10=float(rolling_low(df["low"], 10).iloc[-1]),
        tr=float(tr.iloc[-1]),
        atr_20=float(atr.iloc[-1]),
        adx_14=float(adx(df, 14).iloc[-1]),
        avg_volume_20=float(df["volume"].iloc[-20:].mean()),
        avg_turnover_20=float(turnover.iloc[-20:].mean()),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_indicators.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add turtle/indicators.py tests/test_indicators.py requirements.txt
git commit -m "feat: pure indicator functions (TR, Wilder ATR, rolling high/low, ADX)"
```

---

### Task 3: 신호 분류 (순수 함수)

**Files:**
- Create: `turtle/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: 없음 (스칼라 입력)
- Produces:
  - 상수: `BREAKOUT_TODAY, BREAKOUT_CLOSE, APPROACHING, NEUTRAL, BREAKDOWN` (문자열)
  - `classify(today_high: float, today_low: float, today_close: float, high_55: float, low_20: float, approaching_pct: float) -> str`
  - 우선순위: BREAKOUT_TODAY > BREAKOUT_CLOSE > APPROACHING > BREAKDOWN > NEUTRAL

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_signals.py`)

```python
from turtle.signals import (
    classify,
    BREAKOUT_TODAY,
    BREAKOUT_CLOSE,
    APPROACHING,
    NEUTRAL,
    BREAKDOWN,
)


def test_breakout_today_when_high_crosses_trigger():
    assert classify(today_high=105, today_low=98, today_close=101,
                    high_55=104, low_20=90, approaching_pct=0.98) == BREAKOUT_TODAY


def test_breakout_close_when_only_close_crosses():
    # 고가는 트리거 미달, 종가가 트리거 이상
    assert classify(today_high=103.5, today_low=98, today_close=104,
                    high_55=104, low_20=90, approaching_pct=0.98) == BREAKOUT_CLOSE


def test_approaching_within_2pct():
    # 종가가 트리거의 98% 이상, 트리거 미만
    assert classify(today_high=103, today_low=98, today_close=102,
                    high_55=104, low_20=90, approaching_pct=0.98) == APPROACHING


def test_breakdown_when_low_breaks_low20():
    assert classify(today_high=95, today_low=89, today_close=91,
                    high_55=120, low_20=90, approaching_pct=0.98) == BREAKDOWN


def test_neutral_when_nothing_matches():
    assert classify(today_high=95, today_low=93, today_close=94,
                    high_55=120, low_20=90, approaching_pct=0.98) == NEUTRAL


def test_breakout_today_takes_priority_over_breakdown():
    assert classify(today_high=130, today_low=89, today_close=125,
                    high_55=120, low_20=90, approaching_pct=0.98) == BREAKOUT_TODAY
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_signals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.signals'`

- [ ] **Step 3: 최소 구현** (`turtle/signals.py`)

```python
BREAKOUT_TODAY = "BREAKOUT_TODAY"
BREAKOUT_CLOSE = "BREAKOUT_CLOSE"
APPROACHING = "APPROACHING"
NEUTRAL = "NEUTRAL"
BREAKDOWN = "BREAKDOWN"


def classify(
    today_high: float,
    today_low: float,
    today_close: float,
    high_55: float,
    low_20: float,
    approaching_pct: float,
) -> str:
    if today_high >= high_55:
        return BREAKOUT_TODAY
    if today_close >= high_55:
        return BREAKOUT_CLOSE
    if today_close >= high_55 * approaching_pct:
        return APPROACHING
    if today_low <= low_20:
        return BREAKDOWN
    return NEUTRAL
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_signals.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add turtle/signals.py tests/test_signals.py
git commit -m "feat: signal classification (breakout/approaching/breakdown)"
```

---

### Task 4: 매매 파라미터 (순수 함수)

**Files:**
- Create: `turtle/trading_params.py`
- Test: `tests/test_trading_params.py`

**Interfaces:**
- Consumes: `AccountConfig` (Task 1)
- Produces:
  - `TradingParams` dataclass: `entry_trigger, entry_price_assumed, stop_loss_price, pyramid_1_price, pyramid_2_price, pyramid_3_price, unit_size, unit_notional, max_position_notional, max_loss_per_unit` (float), `tradable: bool`, `note: str`
  - `compute_trading_params(entry_trigger: float, n: float, account: AccountConfig, min_unit: float = 1.0) -> TradingParams`
  - 규칙: `entry_price_assumed = entry_trigger`; `unit_size = floor(total_value*risk_pct/n)`; `unit_size < min_unit` → `tradable=False`, note "매매 불가"

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_trading_params.py`)

```python
import math

from turtle.config import AccountConfig
from turtle.trading_params import compute_trading_params


def _acct():
    return AccountConfig(
        total_value=100_000_000,
        risk_pct=0.01,
        max_units_per_asset=4,
        max_units_correlated=6,
        max_units_total=12,
    )


def test_unit_size_is_floored():
    # risk budget = 1,000,000 ; N=1000 -> 1000주 (floor)
    p = compute_trading_params(entry_trigger=50_000, n=1000, account=_acct())
    assert p.unit_size == 1000
    assert p.tradable is True


def test_stop_and_pyramids():
    p = compute_trading_params(entry_trigger=50_000, n=1000, account=_acct())
    assert p.entry_price_assumed == 50_000
    assert p.stop_loss_price == 50_000 - 2 * 1000        # 48000
    assert p.pyramid_1_price == 50_000 + 0.5 * 1000      # 50500
    assert p.pyramid_2_price == 50_000 + 1.0 * 1000      # 51000
    assert p.pyramid_3_price == 50_000 + 1.5 * 1000      # 51500
    assert p.unit_notional == 1000 * 50_000
    assert p.max_loss_per_unit == 1000 * 2 * 1000


def test_unit_size_below_one_is_not_tradable():
    # N 매우 큼 -> floor(1_000_000 / 2_000_000) = 0
    p = compute_trading_params(entry_trigger=50_000, n=2_000_000, account=_acct())
    assert p.unit_size == 0
    assert p.tradable is False
    assert "매매 불가" in p.note


def test_floor_not_round():
    # risk budget 1,000,000 ; N=3 -> 333333.33 -> floor 333333
    p = compute_trading_params(entry_trigger=10, n=3, account=_acct())
    assert p.unit_size == math.floor(1_000_000 / 3)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_trading_params.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.trading_params'`

- [ ] **Step 3: 최소 구현** (`turtle/trading_params.py`)

```python
import math
from dataclasses import dataclass

from turtle.config import AccountConfig


@dataclass(frozen=True)
class TradingParams:
    entry_trigger: float
    entry_price_assumed: float
    stop_loss_price: float
    pyramid_1_price: float
    pyramid_2_price: float
    pyramid_3_price: float
    unit_size: float
    unit_notional: float
    max_position_notional: float
    max_loss_per_unit: float
    tradable: bool
    note: str


def compute_trading_params(
    entry_trigger: float,
    n: float,
    account: AccountConfig,
    min_unit: float = 1.0,
) -> TradingParams:
    entry = entry_trigger
    if n <= 0:
        return TradingParams(
            entry, entry, 0, 0, 0, 0, 0, 0, 0, 0,
            tradable=False, note="매매 불가 (N=0)",
        )
    risk_budget = account.total_value * account.risk_pct
    unit_size = math.floor(risk_budget / n)
    tradable = unit_size >= min_unit
    note = "" if tradable else "매매 불가 (유닛 수량 < 최소 단위)"
    return TradingParams(
        entry_trigger=entry,
        entry_price_assumed=entry,
        stop_loss_price=entry - 2 * n,
        pyramid_1_price=entry + 0.5 * n,
        pyramid_2_price=entry + 1.0 * n,
        pyramid_3_price=entry + 1.5 * n,
        unit_size=unit_size,
        unit_notional=unit_size * entry,
        max_position_notional=unit_size * entry * account.max_units_per_asset,
        max_loss_per_unit=unit_size * 2 * n,
        tradable=tradable,
        note=note,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_trading_params.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add turtle/trading_params.py tests/test_trading_params.py
git commit -m "feat: trading parameter calc (units floored, stops, pyramids)"
```

---

### Task 5: 데이터 fetcher (ABC + pykrx 어댑터 + 재시도)

**Files:**
- Create: `turtle/data/__init__.py`
- Create: `turtle/data/base.py`
- Create: `turtle/data/krx.py`
- Test: `tests/test_data.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `DataFetcher` ABC: `get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame` (표준 스키마)
  - `normalize_pykrx_ohlcv(raw: pd.DataFrame) -> pd.DataFrame` — pykrx 한글 컬럼(시가/고가/저가/종가/거래량)을 표준 스키마로 변환
  - `with_retry(fn, retries: int = 3, base_delay: float = 1.0)` — exponential backoff 래퍼
  - `KrxFetcher(DataFetcher)` — pykrx `stock.get_market_ohlcv` 사용, `throttle: float = 0.2` 초 sleep

- [ ] **Step 1: pykrx API 형태 확인 (스파이크)**

Run:
```bash
python -c "from pykrx import stock; df=stock.get_market_ohlcv('20260601','20260630','005930'); print(df.columns.tolist()); print(df.head())"
```
Expected: 컬럼에 `['시가','고가','저가','종가','거래량', ...]` 존재, index는 날짜.
컬럼명이 다르면 Step 5의 `normalize_pykrx_ohlcv` 매핑을 실제 값에 맞춰 수정할 것.

- [ ] **Step 2: 실패하는 테스트 작성** (`tests/test_data.py`)

```python
import pandas as pd
import pytest

from turtle.data.base import normalize_pykrx_ohlcv, with_retry


def test_normalize_maps_korean_columns():
    idx = pd.to_datetime(["2026-01-02", "2026-01-03"])
    raw = pd.DataFrame(
        {"시가": [1, 2], "고가": [3, 4], "저가": [0, 1], "종가": [2, 3], "거래량": [10, 20]},
        index=idx,
    )
    out = normalize_pykrx_ohlcv(raw)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out["high"].iloc[1] == 4
    assert str(out.index.dtype).startswith("datetime64")


def test_with_retry_succeeds_after_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert with_retry(flaky, retries=3, base_delay=0) == "ok"
    assert calls["n"] == 3


def test_with_retry_raises_after_exhausting():
    def always_fail():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        with_retry(always_fail, retries=3, base_delay=0)
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/test_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.data'`

- [ ] **Step 4: base.py 구현** (`turtle/data/__init__.py` 빈 파일, `turtle/data/base.py`)

```python
import time
from abc import ABC, abstractmethod

import pandas as pd

_COLMAP = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}


def normalize_pykrx_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=_COLMAP)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def with_retry(fn, retries: int = 3, base_delay: float = 1.0):
    last = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 재시도 목적
            last = exc
            if attempt < retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise last


class DataFetcher(ABC):
    @abstractmethod
    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        ...
```

- [ ] **Step 5: krx.py 구현** (`turtle/data/krx.py`)

```python
import time

import pandas as pd
from pykrx import stock

from turtle.data.base import DataFetcher, normalize_pykrx_ohlcv, with_retry


class KrxFetcher(DataFetcher):
    def __init__(self, throttle: float = 0.2):
        self.throttle = throttle

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        def _call():
            return stock.get_market_ohlcv(start, end, ticker)

        raw = with_retry(_call, retries=3, base_delay=1.0)
        time.sleep(self.throttle)
        return normalize_pykrx_ohlcv(raw)
```
`start`/`end`는 `"YYYYMMDD"` 형식 문자열.

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/test_data.py -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add turtle/data/ tests/test_data.py
git commit -m "feat: data fetcher ABC, pykrx adapter, retry with backoff"
```

---

### Task 6: 거래일 계산 (calendar)

**Files:**
- Create: `turtle/calendar.py`
- Test: `tests/test_calendar.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `resolve_target_date(requested: date | None, business_days: list[date]) -> date` — 요청일이 거래일이 아니면 그 이하 최근 거래일 반환 (순수, 테스트 대상)
  - `lookback_start(target: str, days: int = 320) -> str` — 대상일 기준 달력일 뒤로 이동한 `"YYYYMMDD"` (여유분 포함 조회 시작일)
  - `get_business_days(start: str, end: str) -> list[date]` — pykrx `stock.get_previous_business_days` 또는 OHLCV index 기반 (I/O)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_calendar.py`)

```python
from datetime import date

from turtle.calendar import resolve_target_date, lookback_start


def test_resolve_returns_same_when_business_day():
    bdays = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
    assert resolve_target_date(date(2026, 7, 3), bdays) == date(2026, 7, 3)


def test_resolve_falls_back_to_prior_business_day():
    # 7/4(토),7/5(일) 휴장 -> 7/4 요청 시 7/3 반환
    bdays = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
    assert resolve_target_date(date(2026, 7, 4), bdays) == date(2026, 7, 3)


def test_resolve_none_returns_latest():
    bdays = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
    assert resolve_target_date(None, bdays) == date(2026, 7, 6)


def test_lookback_start_moves_back():
    # 넉넉히 과거로 이동 (정확한 값보다 '이전인지'만 확인)
    assert lookback_start("20260706", days=320) < "20260706"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_calendar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.calendar'`

- [ ] **Step 3: 최소 구현** (`turtle/calendar.py`)

```python
from datetime import date, datetime, timedelta

from pykrx import stock


def resolve_target_date(requested, business_days: list) -> date:
    days = sorted(business_days)
    if requested is None:
        return days[-1]
    eligible = [d for d in days if d <= requested]
    if not eligible:
        raise ValueError("대상일 이전 거래일이 없음")
    return eligible[-1]


def lookback_start(target: str, days: int = 320) -> str:
    d = datetime.strptime(target, "%Y%m%d").date()
    return (d - timedelta(days=days)).strftime("%Y%m%d")


def get_business_days(start: str, end: str) -> list:
    days = stock.get_previous_business_days(fromdate=start, todate=end)
    return [d.date() if isinstance(d, datetime) else d for d in days]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_calendar.py -v`
Expected: PASS

- [ ] **Step 5: get_business_days 스파이크 확인**

Run:
```bash
python -c "from turtle.calendar import get_business_days; print(get_business_days('20260601','20260630')[:5])"
```
Expected: date 리스트 출력. 반환 타입이 다르면 `get_business_days` 변환부 수정.

- [ ] **Step 6: 커밋**

```bash
git add turtle/calendar.py tests/test_calendar.py
git commit -m "feat: trading-day resolution and lookback window"
```

---

### Task 7: 유니버스 필터 (순수 predicate + pykrx 수집)

**Files:**
- Create: `turtle/universe/__init__.py`
- Create: `turtle/universe/filters.py`
- Create: `turtle/universe/krx_stocks.py`
- Create: `turtle/universe/krx_etf.py`
- Test: `tests/test_universe.py`

**Interfaces:**
- Consumes: `StockFilterConfig` (Task 1)
- Produces:
  - `StockMetrics` dataclass: `ticker, name, market, listing_days, avg_turnover_20, avg_volume_20, price, market_cap, is_flagged, is_preferred, is_spac, had_recent_split` (bool 필드 포함)
  - `passes_stock_filters(m: StockMetrics, cfg: StockFilterConfig) -> bool` (순수, 테스트 대상)
  - `build_stock_universe(target: str, cfg: StockFilterConfig, fetcher) -> list[str]` (I/O)
  - `build_etf_universe(target: str, cfg: StockFilterConfig, fetcher) -> list[str]` (I/O)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_universe.py`)

```python
from turtle.config import StockFilterConfig
from turtle.universe.filters import StockMetrics, passes_stock_filters


def _cfg():
    return StockFilterConfig(
        min_listing_days=300,
        min_avg_turnover_20=10_000_000_000,
        min_avg_volume_20=100_000,
        min_price=1000,
        min_market_cap=300_000_000_000,
        kospi_top_n=200,
        kosdaq_top_n=100,
        exclude_preferred=True,
        exclude_spac=True,
        exclude_recent_split=True,
    )


def _good_metrics(**over):
    base = dict(
        ticker="005930", name="삼성전자", market="KOSPI",
        listing_days=5000, avg_turnover_20=50_000_000_000, avg_volume_20=1_000_000,
        price=70_000, market_cap=400_000_000_000_000,
        is_flagged=False, is_preferred=False, is_spac=False, had_recent_split=False,
    )
    base.update(over)
    return StockMetrics(**base)


def test_good_stock_passes():
    assert passes_stock_filters(_good_metrics(), _cfg()) is True


def test_short_listing_fails():
    assert passes_stock_filters(_good_metrics(listing_days=100), _cfg()) is False


def test_low_turnover_fails():
    assert passes_stock_filters(_good_metrics(avg_turnover_20=1_000_000_000), _cfg()) is False


def test_penny_price_fails():
    assert passes_stock_filters(_good_metrics(price=500), _cfg()) is False


def test_small_cap_fails():
    assert passes_stock_filters(_good_metrics(market_cap=100_000_000_000), _cfg()) is False


def test_flagged_fails():
    assert passes_stock_filters(_good_metrics(is_flagged=True), _cfg()) is False


def test_preferred_excluded_when_enabled():
    assert passes_stock_filters(_good_metrics(is_preferred=True), _cfg()) is False


def test_preferred_allowed_when_option_off():
    cfg = _cfg()
    cfg = StockFilterConfig(**{**cfg.__dict__, "exclude_preferred": False})
    assert passes_stock_filters(_good_metrics(is_preferred=True), cfg) is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_universe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.universe'`

- [ ] **Step 3: filters.py 구현** (`turtle/universe/__init__.py` 빈 파일, `turtle/universe/filters.py`)

```python
from dataclasses import dataclass

from turtle.config import StockFilterConfig


@dataclass(frozen=True)
class StockMetrics:
    ticker: str
    name: str
    market: str
    listing_days: int
    avg_turnover_20: float
    avg_volume_20: float
    price: float
    market_cap: float
    is_flagged: bool
    is_preferred: bool
    is_spac: bool
    had_recent_split: bool


def passes_stock_filters(m: StockMetrics, cfg: StockFilterConfig) -> bool:
    if m.listing_days < cfg.min_listing_days:
        return False
    if m.avg_turnover_20 < cfg.min_avg_turnover_20:
        return False
    if m.avg_volume_20 < cfg.min_avg_volume_20:
        return False
    if m.price < cfg.min_price:
        return False
    if m.market_cap < cfg.min_market_cap:
        return False
    if m.is_flagged:
        return False
    if cfg.exclude_preferred and m.is_preferred:
        return False
    if cfg.exclude_spac and m.is_spac:
        return False
    if cfg.exclude_recent_split and m.had_recent_split:
        return False
    return True
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_universe.py -v`
Expected: PASS

- [ ] **Step 5: krx_stocks.py 수집부 구현** (`turtle/universe/krx_stocks.py`)

`StockMetrics`를 pykrx에서 채운다. 시총 상위 N 축소 → 종목별 지표 계산 → `passes_stock_filters` 적용.

```python
import logging
from datetime import datetime

import pandas as pd
from pykrx import stock

from turtle.config import StockFilterConfig
from turtle.universe.filters import StockMetrics, passes_stock_filters

log = logging.getLogger(__name__)

_PREFERRED_SUFFIXES = ("우", "우B")


def _top_by_cap(target: str, market: str, top_n: int) -> pd.DataFrame:
    cap = stock.get_market_cap(target, market=market)  # index=ticker, 시가총액 컬럼
    cap = cap.sort_values("시가총액", ascending=False).head(top_n)
    return cap


def _is_preferred(name: str) -> bool:
    return name.endswith(_PREFERRED_SUFFIXES)


def _is_spac(name: str) -> bool:
    return "스팩" in name


def _build_metrics(ticker: str, target: str, lookback_start: str,
                   market: str, market_cap: float, fetcher) -> StockMetrics:
    df = fetcher.get_ohlcv(ticker, lookback_start, target)
    turnover = (df["close"] * df["volume"]).iloc[-20:].mean()
    name = stock.get_market_ticker_name(ticker)
    flagged = ticker in _flagged_tickers(target, market)
    return StockMetrics(
        ticker=ticker,
        name=name,
        market=market,
        listing_days=len(df),
        avg_turnover_20=float(turnover),
        avg_volume_20=float(df["volume"].iloc[-20:].mean()),
        price=float(df["close"].iloc[-1]),
        market_cap=float(market_cap),
        is_flagged=flagged,
        is_preferred=_is_preferred(name),
        is_spac=_is_spac(name),
        had_recent_split=False,  # MVP: pykrx 미제공 → 보수적으로 False, 로깅으로 대체
    )


def _flagged_tickers(target: str, market: str) -> set:
    """관리종목/투자경고. pykrx 버전에 따라 제공 함수가 다를 수 있어 실패 시 빈 집합."""
    try:
        # 일부 pykrx 버전: stock.get_market_ticker_list(target, market)에는 없음.
        # 관리종목 API 미제공 환경에서는 빈 집합 반환 (로깅).
        return set()
    except Exception as exc:  # noqa: BLE001
        log.warning("flagged ticker 조회 실패: %s", exc)
        return set()


def build_stock_universe(target: str, cfg: StockFilterConfig, fetcher,
                         lookback: str) -> list:
    result = []
    plan = [("KOSPI", cfg.kospi_top_n), ("KOSDAQ", cfg.kosdaq_top_n)]
    for market, top_n in plan:
        cap_df = _top_by_cap(target, market, top_n)
        for ticker, row in cap_df.iterrows():
            try:
                m = _build_metrics(ticker, target, lookback, market,
                                   float(row["시가총액"]), fetcher)
                if passes_stock_filters(m, cfg):
                    result.append(m.ticker)
                    log.info("universe IN  %s %s", m.ticker, m.name)
                else:
                    log.info("universe OUT %s %s", m.ticker, m.name)
            except Exception as exc:  # noqa: BLE001 - 종목별 격리
                log.warning("종목 %s 처리 실패: %s", ticker, exc)
    return result
```
> **주의 (관리종목/액면분할):** pykrx는 관리종목·최근 액면분할 이력을 표준 API로 제공하지 않는다. MVP에서는 `is_flagged=False`, `had_recent_split=False`로 두고 진입/탈락을 로깅한다. 향후 KRX 크롤링 어댑터로 `_flagged_tickers`를 채운다. Step 6 스파이크에서 설치된 pykrx가 `get_market_cap`에 `시가총액` 컬럼을 주는지 확인하고, 다르면 컬럼명을 맞춘다.

- [ ] **Step 6: pykrx 시총 API 스파이크**

Run:
```bash
python -c "from pykrx import stock; c=stock.get_market_cap('20260703', market='KOSPI'); print(c.columns.tolist()); print(c.head(2))"
```
Expected: `시가총액` 컬럼 존재. 다르면 `_top_by_cap` 정렬 컬럼명 수정.

- [ ] **Step 7: krx_etf.py 구현** (`turtle/universe/krx_etf.py`)

ETF는 시총 상위 N·관리종목 개념이 없으므로 유동성·상장기간·가격 필터만 적용.

```python
import logging

from pykrx import stock
from turtle.config import StockFilterConfig
from turtle.data.base import normalize_pykrx_ohlcv

log = logging.getLogger(__name__)


def build_etf_universe(target: str, cfg: StockFilterConfig, fetcher, lookback: str) -> list:
    from pykrx import etf as etf_api

    result = []
    for ticker in etf_api.get_etf_ticker_list(target):
        try:
            raw = etf_api.get_etf_ohlcv_by_date(lookback, target, ticker)
            df = normalize_pykrx_ohlcv(raw)
            if len(df) < cfg.min_listing_days:
                continue
            turnover = (df["close"] * df["volume"]).iloc[-20:].mean()
            volume = df["volume"].iloc[-20:].mean()
            price = df["close"].iloc[-1]
            if (turnover >= cfg.min_avg_turnover_20
                    and volume >= cfg.min_avg_volume_20
                    and price >= cfg.min_price):
                result.append(ticker)
                log.info("etf universe IN  %s", ticker)
        except Exception as exc:  # noqa: BLE001
            log.warning("ETF %s 처리 실패: %s", ticker, exc)
    return result
```
> **스파이크:** `etf_api.get_etf_ohlcv_by_date`의 컬럼명이 주식과 다를 수 있음. 실행 후 `normalize_pykrx_ohlcv`의 `_COLMAP`이 커버하는지 확인. NAV/거래량 컬럼명이 다르면 `_COLMAP` 보강.

- [ ] **Step 8: 커밋**

```bash
git add turtle/universe/ tests/test_universe.py
git commit -m "feat: universe filters (pure predicates) + pykrx stock/etf builders"
```

---

### Task 8: 텔레그램 리포트 (순수 포맷터 + 전송)

**Files:**
- Create: `turtle/report/__init__.py`
- Create: `turtle/report/telegram.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: 없음 (dict 리스트 입력)
- Produces:
  - `ScreenResult` dataclass: `ticker, name, market, close, entry_trigger, n, stop_loss_price, unit_size, unit_notional, status, gap_pct, tradable, note`
  - `format_report(target: str, results: list[ScreenResult], universe_counts: dict) -> str` (순수, 테스트 대상)
  - `send_telegram(text: str, bot_token: str, chat_id: str) -> None` (I/O)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_report.py`)

```python
from turtle.report.telegram import format_report, ScreenResult
from turtle.signals import BREAKOUT_TODAY, APPROACHING


def _r(**over):
    base = dict(
        ticker="005930", name="삼성전자", market="KOSPI", close=71000,
        entry_trigger=70000, n=1500, stop_loss_price=67000,
        unit_size=666, unit_notional=46620000, status=BREAKOUT_TODAY,
        gap_pct=0.0, tradable=True, note="",
    )
    base.update(over)
    return ScreenResult(**base)


def test_report_lists_breakout_section():
    text = format_report(
        "2026-07-06",
        [_r()],
        {"stocks": 120, "etf": 30},
    )
    assert "2026-07-06" in text
    assert "삼성전자" in text
    assert "매수 신호" in text


def test_report_separates_approaching():
    text = format_report(
        "2026-07-06",
        [_r(status=APPROACHING, name="근접주", gap_pct=1.2)],
        {"stocks": 120, "etf": 30},
    )
    assert "관찰" in text
    assert "근접주" in text


def test_report_handles_empty_signals():
    text = format_report("2026-07-06", [], {"stocks": 0, "etf": 0})
    assert "2026-07-06" in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.report'`

- [ ] **Step 3: telegram.py 구현** (`turtle/report/__init__.py` 빈 파일, `turtle/report/telegram.py`)

```python
from dataclasses import dataclass

import requests

from turtle.signals import BREAKOUT_TODAY, BREAKOUT_CLOSE, APPROACHING


@dataclass(frozen=True)
class ScreenResult:
    ticker: str
    name: str
    market: str
    close: float
    entry_trigger: float
    n: float
    stop_loss_price: float
    unit_size: float
    unit_notional: float
    status: str
    gap_pct: float
    tradable: bool
    note: str


def _fmt_won(v: float) -> str:
    return f"{v:,.0f}"


def format_report(target: str, results: list, universe_counts: dict) -> str:
    breakouts = [r for r in results if r.status in (BREAKOUT_TODAY, BREAKOUT_CLOSE)]
    approaching = [r for r in results if r.status == APPROACHING]

    lines = [f"📊 터틀 스크리닝 리포트 — {target}", ""]
    lines.append(
        f"유니버스: 주식 {universe_counts.get('stocks', 0)}개 / "
        f"ETF {universe_counts.get('etf', 0)}개"
    )
    lines.append(f"매수 신호: {len(breakouts)}종목 / 관찰: {len(approaching)}종목")
    lines.append("")

    lines.append("🔥 매수 신호 종목")
    if breakouts:
        for r in breakouts:
            flag = "" if r.tradable else f" ⚠️{r.note}"
            lines.append(
                f"• {r.name}({r.ticker}) {r.status}\n"
                f"  종가 {_fmt_won(r.close)} / 트리거 {_fmt_won(r.entry_trigger)} / "
                f"N {_fmt_won(r.n)}\n"
                f"  손절 {_fmt_won(r.stop_loss_price)} / "
                f"1유닛 {_fmt_won(r.unit_size)}주 ({_fmt_won(r.unit_notional)}원){flag}"
            )
    else:
        lines.append("• 없음")
    lines.append("")

    lines.append("👀 관찰 종목 (2% 이내 근접)")
    if approaching:
        for r in approaching:
            lines.append(
                f"• {r.name}({r.ticker}) 종가 {_fmt_won(r.close)} / "
                f"트리거 {_fmt_won(r.entry_trigger)} / 이격 {r.gap_pct:.2f}%"
            )
    else:
        lines.append("• 없음")

    return "\n".join(lines)


def send_telegram(text: str, bot_token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # 텔레그램 4096자 제한 → 분할 전송
    chunks = [text[i:i + 3500] for i in range(0, len(text), 3500)] or [""]
    for chunk in chunks:
        resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=15)
        resp.raise_for_status()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add turtle/report/ tests/test_report.py
git commit -m "feat: telegram report formatter (pure) and sender"
```

---

### Task 9: 파이프라인 오케스트레이션 + 엔트리포인트

**Files:**
- Create: `turtle/pipeline.py`
- Create: `turtle/main.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: 모든 이전 태스크
- Produces:
  - `screen_ticker(ticker, name, market, df, cfg) -> ScreenResult` (순수, df와 config만 받아 지표→신호→파라미터 결합; 테스트 대상)
  - `run(target: str | None, cfg: Config, fetcher, send: bool = True) -> str` (오케스트레이션)
  - `main()` (argparse: `--date YYYY-MM-DD`, `--no-send`)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_pipeline.py`)

```python
import numpy as np
import pandas as pd

from turtle.config import AccountConfig, StockFilterConfig, Config
from turtle.pipeline import screen_ticker
from turtle.signals import BREAKOUT_TODAY


def _cfg():
    return Config(
        account=AccountConfig(100_000_000, 0.01, 4, 6, 12),
        filters_stocks=StockFilterConfig(300, 1e10, 1e5, 1000, 3e11, 200, 100,
                                         True, True, True),
        approaching_pct=0.98,
        assets={"stocks": True, "etf": True, "crypto": False},
        telegram_chat_id="1",
        telegram_bot_token="t",
    )


def _breakout_df():
    n = 70
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    highs = list(np.linspace(100, 150, n - 1)) + [300]   # 오늘 고가 급등 → 돌파
    lows = [h - 5 for h in highs]
    closes = [h - 1 for h in highs]
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes,
         "volume": [1_000_000] * n},
        index=idx,
    )


def test_screen_ticker_detects_breakout():
    res = screen_ticker("005930", "삼성전자", "KOSPI", _breakout_df(), _cfg())
    assert res.status == BREAKOUT_TODAY
    assert res.entry_trigger > 0
    assert res.n > 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turtle.pipeline'`

- [ ] **Step 3: pipeline.py 구현** (`turtle/pipeline.py`)

```python
import logging

from turtle.calendar import get_business_days, lookback_start, resolve_target_date
from turtle.config import Config
from turtle.indicators import compute_indicators
from turtle.report.telegram import ScreenResult, format_report, send_telegram
from turtle.signals import classify, APPROACHING, BREAKOUT_TODAY, BREAKOUT_CLOSE
from turtle.trading_params import compute_trading_params
from turtle.universe.krx_stocks import build_stock_universe
from turtle.universe.krx_etf import build_etf_universe

log = logging.getLogger(__name__)


def screen_ticker(ticker, name, market, df, cfg: Config) -> ScreenResult:
    ind = compute_indicators(df)
    status = classify(
        today_high=df["high"].iloc[-1],
        today_low=df["low"].iloc[-1],
        today_close=ind.close,
        high_55=ind.high_55,
        low_20=ind.low_20,
        approaching_pct=cfg.approaching_pct,
    )
    params = compute_trading_params(ind.high_55, ind.atr_20, cfg.account)
    gap_pct = (ind.high_55 - ind.close) / ind.high_55 * 100 if ind.high_55 else 0.0
    return ScreenResult(
        ticker=ticker, name=name, market=market, close=ind.close,
        entry_trigger=ind.high_55, n=ind.atr_20,
        stop_loss_price=params.stop_loss_price,
        unit_size=params.unit_size, unit_notional=params.unit_notional,
        status=status, gap_pct=gap_pct,
        tradable=params.tradable, note=params.note,
    )


def _target_str(cfg_date) -> str:
    return cfg_date.strftime("%Y%m%d")


def run(target, cfg: Config, fetcher, send: bool = True) -> str:
    # 대상일 확정
    probe_start = lookback_start(_target_str(target) if target else
                                 __import__("datetime").date.today().strftime("%Y%m%d"),
                                 days=30)
    probe_end = (target or __import__("datetime").date.today()).strftime("%Y%m%d")
    bdays = get_business_days(probe_start, probe_end)
    resolved = resolve_target_date(target, bdays)
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=520)  # ~300거래일 확보 위해 넉넉히

    results = []
    counts = {"stocks": 0, "etf": 0}

    if cfg.assets.get("stocks"):
        tickers = build_stock_universe(target_str, cfg.filters_stocks, fetcher, lookback)
        counts["stocks"] = len(tickers)
        for t in tickers:
            try:
                df = fetcher.get_ohlcv(t, lookback, target_str)
                from pykrx import stock as _s
                results.append(screen_ticker(t, _s.get_market_ticker_name(t),
                                             "STOCK", df, cfg))
            except Exception as exc:  # noqa: BLE001
                log.warning("스크리닝 실패 %s: %s", t, exc)

    if cfg.assets.get("etf"):
        etfs = build_etf_universe(target_str, cfg.filters_stocks, fetcher, lookback)
        counts["etf"] = len(etfs)
        for t in etfs:
            try:
                from pykrx import etf as _e
                raw = _e.get_etf_ohlcv_by_date(lookback, target_str, t)
                from turtle.data.base import normalize_pykrx_ohlcv
                df = normalize_pykrx_ohlcv(raw)
                results.append(screen_ticker(t, _e.get_etf_ticker_name(t) if hasattr(_e, "get_etf_ticker_name") else t,
                                             "ETF", df, cfg))
            except Exception as exc:  # noqa: BLE001
                log.warning("ETF 스크리닝 실패 %s: %s", t, exc)

    # 리포트에는 신호 있는 종목만 (NEUTRAL 제외)
    signalled = [r for r in results
                 if r.status in (BREAKOUT_TODAY, BREAKOUT_CLOSE, APPROACHING)]
    text = format_report(resolved.strftime("%Y-%m-%d"), signalled, counts)
    if send:
        try:
            send_telegram(text, cfg.telegram_bot_token, cfg.telegram_chat_id)
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 전송 실패: %s", exc)
    return text
```

- [ ] **Step 4: main.py 구현** (`turtle/main.py`)

```python
import argparse
import logging
from datetime import datetime

from turtle.config import load_config
from turtle.data.krx import KrxFetcher
from turtle.pipeline import run


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD (기본: 직전 거래일)")
    parser.add_argument("--no-send", action="store_true", help="텔레그램 전송 생략, stdout만")
    args = parser.parse_args()

    target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    cfg = load_config()
    fetcher = KrxFetcher()
    text = run(target, cfg, fetcher, send=not args.no_send)
    print(text)


if __name__ == "__main__":
    main()
```
> 참고: `--date`는 무상태 재계산 특성상 자연히 동작한다(원본 스펙 8.3의 재현성). MVP 리포트 대상은 신호 발생 종목이다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 6: 전체 테스트 실행**

Run: `python -m pytest -v`
Expected: 모든 테스트 PASS

- [ ] **Step 7: 실제 실행 스모크 테스트 (네트워크)**

Run: `python -m turtle.main --date 2026-07-03 --no-send`
Expected: 리포트 텍스트가 stdout에 출력. 오류 시 로그 확인 후 스파이크 단계(Task 5·7)의 pykrx 컬럼명 재확인.

- [ ] **Step 8: 커밋**

```bash
git add turtle/pipeline.py turtle/main.py tests/test_pipeline.py
git commit -m "feat: daily screening pipeline and CLI entrypoint"
```

---

### Task 10: 실행 문서 (README + cron)

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: 없음
- Produces: 없음 (문서)

- [ ] **Step 1: README.md 작성**

```markdown
# 터틀 스크리닝 (MVP)

국내주식·ETF 터틀 시스템2(55일 돌파/20일 청산) 일일 스크리너. 무상태 배치, 텔레그램 알림.

## 설치
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # TELEGRAM_BOT_TOKEN 입력
# config.yaml 의 telegram_chat_id 설정
```

## 실행
```
python -m turtle.main                    # 직전 거래일, 텔레그램 전송
python -m turtle.main --date 2026-07-03  # 특정일 재계산
python -m turtle.main --no-send          # 전송 없이 stdout
```

## 테스트
```
python -m pytest -v
```

## cron (VPS, 장마감 후 16:10 KST)
```
10 16 * * 1-5 cd /path/to/turtle-trading && /path/to/.venv/bin/python -m turtle.main >> run.log 2>&1
```

## 한계 (MVP)
- 관리종목/투자경고·최근 액면분할 필터는 pykrx 미제공으로 미적용(로깅으로 대체).
- 크립토, 직전 돌파 결과 필터, 시스템1 병행은 미포함.
```

- [ ] **Step 2: 커밋**

```bash
git add README.md
git commit -m "docs: README with setup, run, and cron instructions"
```

---

## Self-Review

**Spec coverage:**
- 유니버스 필터(3.1) → Task 7 ✅ (관리종목/액면분할은 pykrx 한계로 로깅 대체, README·plan에 명시)
- 지표(4.1: high_55/low_20/ATR/ADX/avg 등) → Task 2 ✅
- 매매 파라미터(4.2/4.3) → Task 4 ✅ (unit floor, 매매불가)
- 신호 분류(5.1) → Task 3 ✅
- 리포트(6.1) → Task 8 ✅ (평균 N 추이는 무상태라 MVP 제외 — 설계 문서 합의)
- 기술스택(7) → Task 1 requirements ✅
- 성능/rate limit(8.1) → Task 5 throttle ✅
- 재시도·예외격리(8.2) → Task 5 with_retry, Task 7·9 try/except ✅
- 재현성(8.3) → Task 9 `--date` ✅ (무상태라 자연 동작)
- 검증(8.4) → Task 2·3·4 known I/O 테스트, ATR TradingView 대조는 스모크 후 수동 1회 ✅
- 확장성(8.5) → DataFetcher ABC, 순수함수 분리 ✅
- 유의사항(9): 오늘 제외·Wilder·floor·로깅 → Global Constraints + 각 태스크 ✅

**MVP 제외 항목**(크립토, 5.2 필터, PG, 시스템1)은 설계 문서에서 합의됨 — 계획 범위 외.

**Placeholder scan:** 코드 스텝 모두 실제 구현 포함. pykrx 컬럼명 불확실 지점은 "스파이크" 검증 스텝으로 명시(placeholder 아님).

**Type consistency:** `Config`/`AccountConfig`/`StockFilterConfig`(Task1) → Task4·7·9에서 동일 필드 사용. `ScreenResult`(Task8) → Task9에서 생성. `IndicatorResult.atr_20` → Task9에서 N으로 사용. `compute_trading_params(entry_trigger, n, account)` 시그니처 Task4 정의 = Task9 호출 일치. ✅
