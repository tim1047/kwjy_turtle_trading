# 백테스트 엔진 (v1: 단일 종목) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단일 종목 OHLCV 히스토리에 기존 라이브 파이프라인의 신호/사이징 로직을 그대로 적용해 성과(거래 로그 + CAGR/MDD/승률/Profit Factor/거래횟수)를 계산하는 CLI 백테스트 엔진을 만든다.

**Architecture:** `turtle/backtest.py`가 하루 단위 상태 머신(진입/피라미딩/청산)을 담당하되, 신호 계산(`classify`)·지표 계산(`compute_indicators`)·사이징(`compute_trading_params`)은 기존 모듈을 그대로 호출한다. `turtle/backtest_report.py`는 거래 로그를 지표로 집계하고 텍스트로 포맷한다. CLI는 `turtle/backtest.py`의 `main()`에서 기존 `DataFetcher`(KRX/Upbit)로 데이터를 당겨와 엔진을 돌린다.

**Tech Stack:** Python 3.11+, pandas, 프로젝트 기존 의존성 그대로 (신규 의존성 추가 없음)

## Global Constraints

- 단일 종목 백테스트만 지원 (멀티종목/포트폴리오/유니버스 재현은 범위 밖)
- 슬리피지·수수료 없음 — 트리거가/피라미드 레벨가 그대로 체결
- 복리 리사이징 없음 — `account.total_value`는 시뮬레이션 시작 시점 값으로 고정
- 피라미딩 최대 유닛 수는 `config.yaml`의 `account.max_units_per_asset` 그대로 사용
- 신호/지표/사이징 로직은 기존 함수(`turtle.signals.classify`, `turtle.indicators.compute_indicators`, `turtle.trading_params.compute_trading_params`)를 그대로 호출 — 재구현 금지
- SMA200 계산에 필요한 최소 200거래일 워밍업 데이터가 없으면 `ValueError`로 실행 중단 (조용히 건너뛰지 않음)
- 스펙 문서: `docs/superpowers/specs/2026-07-13-backtest-engine-design.md`

---

## Task 1: 데이터 모델 (Unit, OpenPosition, Trade, close_position)

**Files:**
- Create: `turtle/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: 없음 (신규 데이터 모델)
- Produces:
  - `Unit(entry_price: float, size: float, entry_date: str)` — frozen dataclass
  - `OpenPosition(units: list[Unit], n: float, stop_price: float)` — mutable dataclass
  - `Trade(entry_date: str, exit_date: str, entry_price: float, exit_price: float, units: int, size: float, pnl: float, pnl_pct: float, exit_reason: str)` — frozen dataclass
  - `close_position(position: OpenPosition, exit_date: pd.Timestamp, exit_price: float, reason: str) -> Trade`

- [ ] **Step 1: Write the failing test**

Create `tests/test_backtest.py`:

```python
import pandas as pd
import pytest

from turtle.backtest import Unit, OpenPosition, Trade, close_position


def test_close_position_single_unit():
    position = OpenPosition(
        units=[Unit(entry_price=100.0, size=10.0, entry_date="2026-01-01")],
        n=5.0,
        stop_price=90.0,
    )
    trade = close_position(position, pd.Timestamp("2026-01-10"), 120.0, "2N")
    assert trade.entry_date == "2026-01-01"
    assert trade.exit_date == "2026-01-10"
    assert trade.entry_price == 100.0
    assert trade.exit_price == 120.0
    assert trade.units == 1
    assert trade.size == 10.0
    assert trade.pnl == pytest.approx(200.0)  # (120-100)*10
    assert trade.pnl_pct == pytest.approx(20.0)  # (120-100)/100*100
    assert trade.exit_reason == "2N"


def test_close_position_weighted_avg_multi_unit():
    position = OpenPosition(
        units=[
            Unit(entry_price=100.0, size=10.0, entry_date="2026-01-01"),
            Unit(entry_price=110.0, size=10.0, entry_date="2026-01-05"),
        ],
        n=5.0,
        stop_price=100.0,
    )
    trade = close_position(position, pd.Timestamp("2026-01-10"), 130.0, "10D")
    # 평단가 = (100*10 + 110*10) / 20 = 105
    assert trade.entry_price == pytest.approx(105.0)
    assert trade.entry_date == "2026-01-01"  # 최초 진입일 유지
    assert trade.units == 2
    assert trade.size == 20.0
    assert trade.pnl == pytest.approx((130.0 - 105.0) * 20.0)
    assert trade.pnl_pct == pytest.approx((130.0 - 105.0) / 105.0 * 100)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'turtle.backtest'`

- [ ] **Step 3: Write minimal implementation**

Create `turtle/backtest.py`:

```python
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Unit:
    entry_price: float
    size: float
    entry_date: str


@dataclass
class OpenPosition:
    units: list[Unit]
    n: float
    stop_price: float


@dataclass(frozen=True)
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    units: int
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str


def close_position(
    position: OpenPosition, exit_date: pd.Timestamp, exit_price: float, reason: str
) -> Trade:
    total_size = sum(u.size for u in position.units)
    avg_price = sum(u.entry_price * u.size for u in position.units) / total_size
    pnl = (exit_price - avg_price) * total_size
    pnl_pct = (exit_price - avg_price) / avg_price * 100
    return Trade(
        entry_date=position.units[0].entry_date,
        exit_date=exit_date.strftime("%Y-%m-%d"),
        entry_price=avg_price,
        exit_price=exit_price,
        units=len(position.units),
        size=total_size,
        pnl=pnl,
        pnl_pct=pnl_pct,
        exit_reason=reason,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add turtle/backtest.py tests/test_backtest.py
git commit -m "feat: add backtest position/trade data models"
```

---

## Task 2: enter_position

**Files:**
- Modify: `turtle/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `Unit`, `OpenPosition` (Task 1); `turtle.signals.classify/BREAKOUT_TODAY/BREAKOUT_CLOSE`; `turtle.trading_params.compute_trading_params`; `turtle.indicators.IndicatorResult`; `turtle.config.AccountConfig`
- Produces: `enter_position(row: pd.Series, ind: IndicatorResult, day: pd.Timestamp, account: AccountConfig, min_unit: float, approaching_pct: float) -> OpenPosition | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
from turtle.backtest import enter_position
from turtle.config import AccountConfig
from turtle.indicators import IndicatorResult


def _acct(max_units=4):
    return AccountConfig(
        total_value=100_000_000, risk_pct=0.01, max_units_per_asset=max_units,
        max_units_correlated=6, max_units_total=12,
    )


def _ind(**overrides):
    base = dict(
        close=104.0, high_55=100.0, low_20=80.0, high_20=100.0, low_10=90.0,
        tr=2.0, atr_20=2.0, adx_14=25.0, avg_volume_20=1000.0,
        avg_turnover_20=100000.0, sma_200=90.0,
    )
    base.update(overrides)
    return IndicatorResult(**base)


def _row(high, low, close):
    return pd.Series({"open": close, "high": high, "low": low, "close": close, "volume": 1000.0})


def test_enter_position_on_breakout():
    ind = _ind()
    row = _row(high=105.0, low=99.0, close=104.0)  # high(105) >= high_55(100)
    day = pd.Timestamp("2026-01-01")
    position = enter_position(row, ind, day, _acct(), min_unit=1.0, approaching_pct=0.98)
    assert position is not None
    assert len(position.units) == 1
    assert position.units[0].entry_price == 100.0  # 트리거가(high_55) 체결, 당일 고가 아님
    assert position.units[0].entry_date == "2026-01-01"
    assert position.n == 2.0
    assert position.stop_price == 100.0 - 2 * 2.0  # 96.0


def test_no_entry_when_no_breakout():
    ind = _ind()
    row = _row(high=95.0, low=90.0, close=93.0)  # 트리거 미달
    day = pd.Timestamp("2026-01-01")
    position = enter_position(row, ind, day, _acct(), min_unit=1.0, approaching_pct=0.98)
    assert position is None


def test_no_entry_when_not_tradable():
    # N이 매우 커서 유닛 사이즈가 0으로 내림됨 -> 매매 불가
    ind = _ind(atr_20=50_000_000.0)
    row = _row(high=105.0, low=99.0, close=104.0)
    day = pd.Timestamp("2026-01-01")
    position = enter_position(row, ind, day, _acct(), min_unit=1.0, approaching_pct=0.98)
    assert position is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backtest.py -v -k enter_position`
Expected: FAIL with `ImportError: cannot import name 'enter_position'`

- [ ] **Step 3: Write minimal implementation**

Append to `turtle/backtest.py` (add imports at top, add function at bottom):

```python
from turtle.config import AccountConfig
from turtle.indicators import IndicatorResult
from turtle.signals import BREAKOUT_CLOSE, BREAKOUT_TODAY, classify
from turtle.trading_params import compute_trading_params


def enter_position(
    row: pd.Series,
    ind: IndicatorResult,
    day: pd.Timestamp,
    account: AccountConfig,
    min_unit: float,
    approaching_pct: float,
) -> OpenPosition | None:
    status = classify(
        today_high=float(row["high"]),
        today_low=float(row["low"]),
        today_close=float(row["close"]),
        high_55=ind.high_55,
        low_20=ind.low_20,
        approaching_pct=approaching_pct,
        sma_200=ind.sma_200,
    )
    if status not in (BREAKOUT_TODAY, BREAKOUT_CLOSE):
        return None
    params = compute_trading_params(ind.high_55, ind.atr_20, account, min_unit)
    if not params.tradable:
        return None
    unit = Unit(entry_price=ind.high_55, size=params.unit_size, entry_date=day.strftime("%Y-%m-%d"))
    return OpenPosition(units=[unit], n=ind.atr_20, stop_price=params.stop_loss_price)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add turtle/backtest.py tests/test_backtest.py
git commit -m "feat: add backtest entry logic"
```

---

## Task 3: add_pyramid_unit

**Files:**
- Modify: `turtle/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `Unit`, `OpenPosition` (Task 1); `compute_trading_params` (Task 2 import)
- Produces: `add_pyramid_unit(position: OpenPosition, row: pd.Series, day: pd.Timestamp, account: AccountConfig, min_unit: float) -> None` (in-place 수정, 반환값 없음)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
from turtle.backtest import add_pyramid_unit


def test_add_pyramid_unit_when_price_reaches_level():
    position = OpenPosition(
        units=[Unit(entry_price=100.0, size=10000.0, entry_date="2026-01-01")],
        n=2.0,
        stop_price=96.0,
    )
    # pyramid_1_price = 100 + 0.5*2 = 101
    row = pd.Series({"open": 101.0, "high": 102.0, "low": 100.5, "close": 101.0})
    day = pd.Timestamp("2026-01-02")
    add_pyramid_unit(position, row, day, _acct(), min_unit=1.0)
    assert len(position.units) == 2
    assert position.units[1].entry_price == 101.0
    assert position.units[1].entry_date == "2026-01-02"
    assert position.stop_price == 101.0 - 2 * 2.0  # 97.0


def test_no_pyramid_when_price_below_level():
    position = OpenPosition(
        units=[Unit(entry_price=100.0, size=10000.0, entry_date="2026-01-01")],
        n=2.0,
        stop_price=96.0,
    )
    row = pd.Series({"open": 100.5, "high": 100.8, "low": 100.0, "close": 100.5})  # < 101
    day = pd.Timestamp("2026-01-02")
    add_pyramid_unit(position, row, day, _acct(), min_unit=1.0)
    assert len(position.units) == 1
    assert position.stop_price == 96.0


def test_no_pyramid_when_max_units_reached():
    position = OpenPosition(
        units=[
            Unit(entry_price=100.0, size=1.0, entry_date="2026-01-01"),
            Unit(entry_price=101.0, size=1.0, entry_date="2026-01-02"),
        ],
        n=2.0,
        stop_price=97.0,
    )
    row = pd.Series({"open": 110.0, "high": 111.0, "low": 109.0, "close": 110.0})
    day = pd.Timestamp("2026-01-03")
    add_pyramid_unit(position, row, day, _acct(max_units=2), min_unit=1.0)
    assert len(position.units) == 2  # max_units_per_asset=2라 추가 안 됨
    assert position.stop_price == 97.0


def test_no_pyramid_when_all_three_levels_used():
    position = OpenPosition(
        units=[
            Unit(entry_price=100.0, size=1.0, entry_date="2026-01-01"),
            Unit(entry_price=101.0, size=1.0, entry_date="2026-01-02"),
            Unit(entry_price=102.0, size=1.0, entry_date="2026-01-03"),
            Unit(entry_price=103.0, size=1.0, entry_date="2026-01-04"),
        ],
        n=2.0,
        stop_price=99.0,
    )
    row = pd.Series({"open": 200.0, "high": 201.0, "low": 199.0, "close": 200.0})
    day = pd.Timestamp("2026-01-05")
    add_pyramid_unit(position, row, day, _acct(max_units=4), min_unit=1.0)
    assert len(position.units) == 4  # 이미 4유닛(max) -> 더 추가 안 됨
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backtest.py -v -k pyramid`
Expected: FAIL with `ImportError: cannot import name 'add_pyramid_unit'`

- [ ] **Step 3: Write minimal implementation**

Append to `turtle/backtest.py`:

```python
def add_pyramid_unit(
    position: OpenPosition,
    row: pd.Series,
    day: pd.Timestamp,
    account: AccountConfig,
    min_unit: float,
) -> None:
    if len(position.units) >= account.max_units_per_asset:
        return
    first_entry = position.units[0].entry_price
    params = compute_trading_params(first_entry, position.n, account, min_unit)
    levels = [params.pyramid_1_price, params.pyramid_2_price, params.pyramid_3_price]
    idx = len(position.units) - 1
    if idx >= len(levels):
        return
    level = levels[idx]
    if float(row["close"]) >= level:
        position.units.append(
            Unit(entry_price=level, size=params.unit_size, entry_date=day.strftime("%Y-%m-%d"))
        )
        position.stop_price = level - 2 * position.n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add turtle/backtest.py tests/test_backtest.py
git commit -m "feat: add backtest pyramiding logic"
```

---

## Task 4: check_exit

**Files:**
- Modify: `turtle/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `OpenPosition`, `Trade`, `close_position` (Task 1); `IndicatorResult` (Task 2 import)
- Produces: `check_exit(position: OpenPosition, row: pd.Series, ind: IndicatorResult, day: pd.Timestamp) -> Trade | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
from turtle.backtest import check_exit


def test_check_exit_no_breach():
    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=96.0)
    row = pd.Series({"close": 99.0})
    trade = check_exit(position, row, _ind(low_10=95.0), pd.Timestamp("2026-01-05"))
    assert trade is None


def test_check_exit_breach_2n_only():
    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=96.0)
    row = pd.Series({"close": 95.0})  # <= stop_price(96), > low_10(90)
    trade = check_exit(position, row, _ind(low_10=90.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "2N"
    assert trade.exit_price == 95.0
    assert trade.exit_date == "2026-01-05"


def test_check_exit_breach_10d_only():
    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=80.0)
    row = pd.Series({"close": 85.0})  # > stop_price(80), <= low_10(90)
    trade = check_exit(position, row, _ind(low_10=90.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "10D"


def test_check_exit_breach_both():
    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=96.0)
    row = pd.Series({"close": 80.0})  # <= both
    trade = check_exit(position, row, _ind(low_10=90.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "2N+10D"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backtest.py -v -k check_exit`
Expected: FAIL with `ImportError: cannot import name 'check_exit'`

- [ ] **Step 3: Write minimal implementation**

Append to `turtle/backtest.py`:

```python
def check_exit(
    position: OpenPosition, row: pd.Series, ind: IndicatorResult, day: pd.Timestamp
) -> Trade | None:
    close = float(row["close"])
    breach_2n = close <= position.stop_price
    breach_10d = close <= ind.low_10
    if not (breach_2n or breach_10d):
        return None
    if breach_2n and breach_10d:
        reason = "2N+10D"
    elif breach_2n:
        reason = "2N"
    else:
        reason = "10D"
    return close_position(position, day, close, reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add turtle/backtest.py tests/test_backtest.py
git commit -m "feat: add backtest stop-loss exit logic"
```

---

## Task 5: run_backtest (일별 루프 + 워밍업 검증)

**Files:**
- Modify: `turtle/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `enter_position` (Task 2), `add_pyramid_unit` (Task 3), `check_exit` (Task 4), `turtle.indicators.compute_indicators`
- Produces: `run_backtest(df: pd.DataFrame, start: str, end: str, account: AccountConfig, min_unit: float = 1.0, approaching_pct: float = 0.98) -> list[Trade]` — `start`/`end`는 `"YYYYMMDD"` 문자열, `df`는 `start` 이전 워밍업 데이터를 포함한 표준 스키마 OHLCV. SMA200 워밍업 부족 시 `ValueError`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
from turtle.backtest import run_backtest
from turtle.indicators import compute_indicators


def _flat_then_breakout_df(breakout_idx: int, n: int, post_breakout_closes: dict):
    """기본 흐름은 high=101/low=99/close=100 평평한 흐름. breakout_idx일에 high를
    트리거(101) 위로 살짝 올리고, post_breakout_closes={offset: close}로 이후
    일자의 종가를 덮어쓴다 (high=close+1, low=close-1 패턴 유지).

    row 200(테스트의 start_idx)부터 breakout_idx 직전까지는 high를 100.9로 살짝
    눌러둔다 — 그렇지 않으면 트레일링 high_55도 101.0이라 오늘 high(101.0)가
    `>=` 비교로 그 값과 정확히 같아져, 평가되는 첫날(row200)부터 스퓨리어스
    돌파가 발생한다. row 200 이전(0~199) 구간은 101.0을 유지해 트레일링
    55일 윈도우 안에서 저항선(high_55=101.0) 역할을 하도록 남겨둔다."""
    idx = pd.bdate_range("2020-01-01", periods=n)
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [100.0] * n
    for i in range(200, breakout_idx):
        highs[i] = 100.9
    highs[breakout_idx] = 101.5
    for offset, close in post_breakout_closes.items():
        i = breakout_idx + offset
        closes[i] = close
        highs[i] = close + 1.0
        lows[i] = close - 1.0
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": [1_000_000.0] * n},
        index=idx,
    )


def test_run_backtest_entry_pyramid_and_exit():
    n = 230
    breakout_idx = 205  # sma_200 워밍업(200일) 이후, 여유 있게
    df = _flat_then_breakout_df(
        breakout_idx, n,
        post_breakout_closes={1: 103.0, 2: 80.0},  # 1일 후 피라미드 추가, 2일 후 급락 청산
    )
    start = df.index[200].strftime("%Y%m%d")
    end = df.index[breakout_idx + 3].strftime("%Y%m%d")

    trades = run_backtest(df, start, end, _acct(), min_unit=1.0, approaching_pct=0.98)

    assert len(trades) == 1
    trade = trades[0]

    # 오라클: 이미 단위 테스트로 검증된 compute_indicators/compute_trading_params를
    # 그대로 호출해 기대값을 계산 (run_backtest도 내부적으로 동일 함수를 호출함)
    entry_ind = compute_indicators(df.iloc[: breakout_idx + 1])
    entry_params = compute_trading_params(entry_ind.high_55, entry_ind.atr_20, _acct(), 1.0)
    expected_pyramid_1 = entry_params.pyramid_1_price
    assert expected_pyramid_1 < 103.0  # offset=1의 종가(103.0)가 피라미드 레벨을 넘긴다는 전제 검증

    assert trade.entry_date == df.index[breakout_idx].strftime("%Y-%m-%d")
    assert trade.exit_date == df.index[breakout_idx + 2].strftime("%Y-%m-%d")
    assert trade.units == 2
    assert trade.exit_reason == "2N+10D"
    assert trade.exit_price == 80.0

    expected_avg = (entry_ind.high_55 + expected_pyramid_1) / 2
    expected_size = 2 * entry_params.unit_size
    assert trade.entry_price == pytest.approx(expected_avg)
    assert trade.size == pytest.approx(expected_size)
    assert trade.pnl == pytest.approx((80.0 - expected_avg) * expected_size)


def test_run_backtest_raises_when_warmup_insufficient():
    n = 50  # 200일 미달
    idx = pd.bdate_range("2020-01-01", periods=n)
    df = pd.DataFrame(
        {"open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
         "close": [100.0] * n, "volume": [1000.0] * n},
        index=idx,
    )
    with pytest.raises(ValueError, match="워밍업"):
        run_backtest(df, df.index[40].strftime("%Y%m%d"), df.index[45].strftime("%Y%m%d"), _acct())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backtest.py -v -k run_backtest`
Expected: FAIL with `ImportError: cannot import name 'run_backtest'`

- [ ] **Step 3: Write minimal implementation**

Append to `turtle/backtest.py` (add `datetime` import at top, add function at bottom):

```python
from datetime import datetime

from turtle.indicators import compute_indicators


def run_backtest(
    df: pd.DataFrame,
    start: str,
    end: str,
    account: AccountConfig,
    min_unit: float = 1.0,
    approaching_pct: float = 0.98,
) -> list[Trade]:
    df = df.sort_index()
    start_dt = pd.Timestamp(datetime.strptime(start, "%Y%m%d"))
    end_dt = pd.Timestamp(datetime.strptime(end, "%Y%m%d"))
    start_idx = int(df.index.searchsorted(start_dt, side="left"))
    if start_idx >= len(df) or df.index[start_idx] > end_dt:
        raise ValueError(f"{start}~{end} 구간에 데이터가 없음")

    warmup_ind = compute_indicators(df.iloc[: start_idx + 1])
    if warmup_ind.sma_200 != warmup_ind.sma_200:  # NaN
        raise ValueError("워밍업 데이터 부족 (SMA200 계산에 최소 200거래일 필요)")

    trades: list[Trade] = []
    position: OpenPosition | None = None

    for i in range(start_idx, len(df)):
        day = df.index[i]
        if day > end_dt:
            break
        row = df.iloc[i]
        ind = compute_indicators(df.iloc[: i + 1])

        if position is not None:
            trade = check_exit(position, row, ind, day)
            if trade is not None:
                trades.append(trade)
                position = None

        if position is None:
            position = enter_position(row, ind, day, account, min_unit, approaching_pct)
        else:
            add_pyramid_unit(position, row, day, account, min_unit)

    return trades
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add turtle/backtest.py tests/test_backtest.py
git commit -m "feat: add backtest day-by-day simulation loop"
```

---

## Task 6: backtest_report.py (지표 계산 + 텍스트 포맷)

**Files:**
- Create: `turtle/backtest_report.py`
- Test: `tests/test_backtest_report.py`

**Interfaces:**
- Consumes: `turtle.backtest.Trade` (Task 1)
- Produces:
  - `BacktestMetrics(total_trades: int, win_rate: float, profit_factor: float, cagr: float, mdd: float)` — frozen dataclass
  - `compute_metrics(trades: list[Trade], initial_capital: float, start: str, end: str) -> BacktestMetrics`
  - `format_backtest_report(ticker: str, start: str, end: str, trades: list[Trade], metrics: BacktestMetrics) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_backtest_report.py`:

```python
import pytest

from turtle.backtest import Trade
from turtle.backtest_report import compute_metrics, format_backtest_report


def _trade(entry_date, exit_date, pnl):
    return Trade(
        entry_date=entry_date, exit_date=exit_date, entry_price=100.0,
        exit_price=100.0 + pnl / 10.0, units=1, size=10.0, pnl=pnl,
        pnl_pct=pnl / 1000.0 * 100, exit_reason="2N",
    )


def test_compute_metrics_all_wins():
    trades = [_trade("2020-01-01", "2020-02-01", 100_000.0), _trade("2020-02-01", "2020-03-01", 50_000.0)]
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20201231")
    assert metrics.total_trades == 2
    assert metrics.win_rate == pytest.approx(100.0)
    assert metrics.profit_factor == float("inf")
    assert metrics.mdd == pytest.approx(0.0)  # 계속 상승만 했으므로 낙폭 없음


def test_compute_metrics_mixed():
    trades = [
        _trade("2020-01-01", "2020-02-01", 200_000.0),   # 1,000,000 -> 1,200,000
        _trade("2020-02-01", "2020-03-01", -300_000.0),  # -> 900,000 (peak 1,200,000 대비 -25%)
        _trade("2020-03-01", "2020-04-01", 100_000.0),   # -> 1,000,000
    ]
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20201231")
    assert metrics.total_trades == 3
    assert metrics.win_rate == pytest.approx(200 / 3, rel=1e-3)  # 2/3 승
    assert metrics.profit_factor == pytest.approx(1.0)  # gross_profit 300,000 / gross_loss 300,000
    assert metrics.mdd == pytest.approx(25.0)  # (1,200,000-900,000)/1,200,000*100


def test_compute_metrics_no_trades():
    metrics = compute_metrics([], initial_capital=1_000_000.0, start="20200101", end="20201231")
    assert metrics.total_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.cagr == 0.0
    assert metrics.mdd == 0.0


def test_compute_metrics_cagr_simple():
    trades = [_trade("2020-01-01", "2021-01-01", 1_000_000.0)]  # 1,000,000 -> 2,000,000 (100% 수익)
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20210101")
    # 약 1년(366일, 2020년 윤년) 기간의 100% 수익 -> CAGR ≈ 100%
    assert metrics.cagr == pytest.approx(100.0, rel=0.01)


def test_format_backtest_report_includes_summary_and_trades():
    trades = [_trade("2020-01-01", "2020-02-01", 100_000.0)]
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20201231")
    text = format_backtest_report("005930", "20200101", "20201231", trades, metrics)
    assert "005930" in text
    assert "2020-01-01" in text
    assert "2020-02-01" in text
    assert "1" in text  # total_trades


def test_format_backtest_report_no_trades():
    metrics = compute_metrics([], initial_capital=1_000_000.0, start="20200101", end="20201231")
    text = format_backtest_report("005930", "20200101", "20201231", [], metrics)
    assert "거래 없음" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backtest_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'turtle.backtest_report'`

- [ ] **Step 3: Write minimal implementation**

Create `turtle/backtest_report.py`:

```python
from dataclasses import dataclass
from datetime import datetime

from turtle.backtest import Trade


@dataclass(frozen=True)
class BacktestMetrics:
    total_trades: int
    win_rate: float
    profit_factor: float
    cagr: float
    mdd: float


def compute_metrics(
    trades: list[Trade], initial_capital: float, start: str, end: str
) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics(total_trades=0, win_rate=0.0, profit_factor=0.0, cagr=0.0, mdd=0.0)

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100

    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    # 실현손익 누적 기준 자본곡선 (거래 청산 시점만 스텝) — 보유 중 미실현 손익은
    # v1에서 반영하지 않는다 (설계 문서의 단순화 결정과 동일 선상).
    equity = initial_capital
    curve = [initial_capital]
    for t in sorted(trades, key=lambda t: t.exit_date):
        equity += t.pnl
        curve.append(equity)
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)

    start_dt = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    years = max((end_dt - start_dt).days / 365.25, 1 / 365.25)
    final_capital = curve[-1]
    if initial_capital > 0 and final_capital > 0:
        cagr = ((final_capital / initial_capital) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    return BacktestMetrics(
        total_trades=len(trades), win_rate=win_rate, profit_factor=profit_factor,
        cagr=cagr, mdd=mdd,
    )


def format_backtest_report(
    ticker: str, start: str, end: str, trades: list[Trade], metrics: BacktestMetrics
) -> str:
    lines = [f"백테스트 리포트 — {ticker} ({start}~{end})", ""]
    lines.append(
        f"거래 {metrics.total_trades}회 · 승률 {metrics.win_rate:.1f}% · "
        f"Profit Factor {metrics.profit_factor:.2f} · CAGR {metrics.cagr:.1f}% · MDD {metrics.mdd:.1f}%"
    )
    lines.append("")
    if not trades:
        lines.append("거래 없음")
        return "\n".join(lines)
    for t in trades:
        lines.append(
            f"{t.entry_date} → {t.exit_date} · {t.units}유닛 · "
            f"진입 {t.entry_price:,.0f} → 청산 {t.exit_price:,.0f} "
            f"({t.exit_reason}) · 손익 {t.pnl:,.0f} ({t.pnl_pct:+.2f}%)"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backtest_report.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add turtle/backtest_report.py tests/test_backtest_report.py
git commit -m "feat: add backtest metrics and report formatting"
```

---

## Task 7: CLI 진입점

**Files:**
- Modify: `turtle/backtest.py`

**Interfaces:**
- Consumes: `run_backtest` (Task 5), `compute_metrics`/`format_backtest_report` (Task 6), `turtle.config.load_config`, `turtle.data.krx.KrxFetcher`, `turtle.data.upbit.UpbitFetcher`, `turtle.calendar.lookback_start`
- Produces: `main()` — CLI 진입점, 자동화 테스트 없음 (실데이터 I/O 필요, 설계 문서 명시)

- [ ] **Step 1: Write the CLI entrypoint**

Append to `turtle/backtest.py` (add imports at top, add `main()` + `if __name__` guard at bottom):

```python
import argparse

from turtle.backtest_report import compute_metrics, format_backtest_report
from turtle.calendar import lookback_start
from turtle.config import load_config
from turtle.data.krx import KrxFetcher
from turtle.data.upbit import UpbitFetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="터틀 트레이딩 단일 종목 백테스트")
    parser.add_argument("--ticker", required=True, help="종목/코인 코드 (예: 005930, KRW-BTC)")
    parser.add_argument("--market", required=True, choices=["STOCK", "ETF", "CRYPTO"])
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    args = parser.parse_args()

    cfg = load_config()
    fetcher = UpbitFetcher() if args.market == "CRYPTO" else KrxFetcher()
    lookback = lookback_start(args.start, days=520)
    df = fetcher.get_ohlcv(args.ticker, lookback, args.end)
    min_unit = cfg.filters_crypto.min_unit if args.market == "CRYPTO" else 1.0

    trades = run_backtest(df, args.start, args.end, cfg.account, min_unit, cfg.approaching_pct)
    metrics = compute_metrics(trades, cfg.account.total_value, args.start, args.end)
    print(format_backtest_report(args.ticker, args.start, args.end, trades, metrics))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full test suite to verify no regressions**

Run: `python -m pytest -v`
Expected: PASS (전체, 기존 테스트 포함 회귀 없음)

- [ ] **Step 3: Manual smoke test with real data**

Run:
```bash
python -m turtle.backtest --ticker 005930 --market STOCK --start 20220101 --end 20261231
```
Expected: 콘솔에 "백테스트 리포트 — 005930 (20220101~20261231)"로 시작하는 텍스트 출력,
거래 로그와 요약 지표(거래 횟수/승률/Profit Factor/CAGR/MDD)가 표시됨. 에러 없이 종료.
결과 수치가 합리적 범위인지(예: 승률 0~100%, MDD 0~100%) 육안 확인.

- [ ] **Step 4: Commit**

```bash
git add turtle/backtest.py
git commit -m "feat: add backtest CLI entrypoint"
```

---

## Self-Review Notes

- **스펙 커버리지:** 아키텍처(Task1,5,7) / 포지션·피라미드·스탑 관리(Task2,3,4) / 체결가 가정(Task2,3에서 트리거·레벨가 그대로 사용) / 자본·사이징(Task2,3에서 `compute_trading_params` 재사용, `total_value` 고정) / 리포트(Task6) / 에러 처리(Task5의 워밍업 `ValueError`, 루프 내부는 예외 전파) / 테스트(Task1-6 단위 테스트 + Task7 수동 스모크) — 스펙의 전 섹션이 태스크에 매핑됨.
- **플레이스홀더 스캔:** 없음 — 모든 스텝에 실행 가능한 코드/명령 포함.
- **타입 일관성:** `OpenPosition`/`Unit`/`Trade`는 Task 1에서 정의된 필드명을 Task 2~7까지 동일하게 사용 (`entry_price`, `size`, `entry_date`, `stop_price`, `pnl`, `exit_reason` 등 재정의 없음). `run_backtest`의 반환 타입(`list[Trade]`)은 Task 6의 `compute_metrics` 첫 인자 타입과 일치.
