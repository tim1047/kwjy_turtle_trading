"""여러 종목의 특정 구간을 pykrx로 조회해 캔들패턴·거래량·이평선을 계산하고,
급등일(anchor) 기준 공통 패턴을 집계하는 일회성 분석 스크립트.

사용법:
    python tools/pattern_scan.py 005930 000660 --start 20260101 --end 20260819
    python tools/pattern_scan.py 005930 --anchor-pct 12 --pre 5
    python tools/pattern_scan.py --selftest

파이프라인(turtle/swing)과 분리된 조사용 도구다 — 시그널 생성이나 DB 기록은 하지 않는다.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from turtle.indicators import adx, atr_wilder, true_range  # noqa: E402

MA_WINDOWS = (5, 20, 60, 120)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """표준 스키마 OHLCV에 캔들·거래량·이평선 피처를 붙인다 (순수 함수)."""
    o, h, l, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    rng = (h - l).replace(0, np.nan)
    body = (c - o).abs()
    prev_o, prev_c = o.shift(1), c.shift(1)

    f = pd.DataFrame(index=df.index)
    f["close"] = c
    f["chg_pct"] = c.pct_change() * 100
    f["body_pct"] = (c - o) / o * 100
    f["body_ratio"] = body / rng                      # 몸통/전체범위
    f["upper_wick"] = (h - np.maximum(o, c)) / rng
    f["lower_wick"] = (np.minimum(o, c) - l) / rng
    f["close_pos"] = (c - l) / rng                    # 종가 위치(1=고가마감)

    # 캔들패턴 플래그
    f["bullish"] = c > o
    f["marubozu_bull"] = (c > o) & (f["body_ratio"] > 0.7) & (f["close_pos"] > 0.8)
    f["hammer"] = (f["lower_wick"] > 0.5) & (f["body_ratio"] < 0.35) & (f["upper_wick"] < 0.2)
    f["doji"] = f["body_ratio"] < 0.1
    f["engulfing_bull"] = (c > o) & (prev_c < prev_o) & (c >= prev_o) & (o <= prev_c)
    f["inside_bar"] = (h <= h.shift(1)) & (l >= l.shift(1))
    f["gap_up"] = o > h.shift(1)

    # 거래량
    vol_ma20 = v.rolling(20).mean()
    f["vol"] = v
    f["vol_ratio_20"] = v / vol_ma20                  # 20일 평균 대비 배수
    f["vol_dry"] = f["vol_ratio_20"] < 0.7
    f["turnover_eok"] = c * v / 1e8                   # 거래대금(억원)

    # 이평선
    for w in MA_WINDOWS:
        f[f"ma{w}"] = c.rolling(w).mean()
    f["ma_aligned"] = (f["ma5"] > f["ma20"]) & (f["ma20"] > f["ma60"]) & (f["ma60"] > f["ma120"])
    f["above_ma20"] = c > f["ma20"]
    f["above_ma60"] = c > f["ma60"]
    f["disparity_20"] = c / f["ma20"] * 100           # 20일 이격도
    f["ma20_slope5"] = f["ma20"].pct_change(5) * 100

    # 추세/변동성
    f["adx14"] = adx(df, 14)
    f["atr_pct"] = atr_wilder(true_range(df), 20) / c * 100
    return f


BOOL_COLS = [
    "marubozu_bull", "hammer", "doji", "engulfing_bull", "inside_bar", "gap_up",
    "ma_aligned", "above_ma20", "above_ma60",
]
NUM_COLS = [
    "chg_pct", "body_ratio", "close_pos", "upper_wick", "lower_wick",
    "vol_ratio_20", "disparity_20", "ma20_slope5", "adx14", "atr_pct", "turnover_eok",
]


def find_anchors(f: pd.DataFrame, pct: float, vol_x: float) -> pd.DatetimeIndex:
    """급등일 = 상승률 >= pct AND 거래량 >= 20일평균 * vol_x."""
    hit = (f["chg_pct"] >= pct) & (f["vol_ratio_20"] >= vol_x)
    return f.index[hit.fillna(False)]


def event_rows(f: pd.DataFrame, ticker: str, anchors, pre: int) -> pd.DataFrame:
    """anchor별 D-pre..D 구간을 offset 라벨(-n..0)로 펼친 롱포맷."""
    out = []
    pos = {d: i for i, d in enumerate(f.index)}
    for a in anchors:
        i = pos[a]
        if i < pre:
            continue
        for off in range(-pre, 1):
            row = f.iloc[i + off].to_dict()
            row.update(ticker=ticker, anchor=a.date(), offset=off, date=f.index[i + off].date())
            out.append(row)
    return pd.DataFrame(out)


def summarize(ev: pd.DataFrame) -> pd.DataFrame:
    """offset별 공통점 집계: bool은 발생비율(%), 수치는 중앙값."""
    g = ev.groupby("offset")
    bools = g[BOOL_COLS].mean() * 100
    nums = g[NUM_COLS].median()
    n = g.size().rename("n")
    return pd.concat([n, bools.round(0), nums.round(2)], axis=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pykrx 다종목 패턴 공통점 분석")
    ap.add_argument("tickers", nargs="*", help="6자리 종목코드")
    ap.add_argument("--start", required=False, help="YYYYMMDD")
    ap.add_argument("--end", required=False, help="YYYYMMDD")
    ap.add_argument("--anchor-pct", type=float, default=8.0, help="급등일 기준 상승률(%%)")
    ap.add_argument("--anchor-vol", type=float, default=2.0, help="급등일 기준 거래량 배수")
    ap.add_argument("--pre", type=int, default=5, help="급등일 이전 관찰 거래일 수")
    ap.add_argument("--csv", help="이벤트 상세를 저장할 CSV 경로")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    if not a.tickers or not a.start or not a.end:
        ap.error("tickers, --start, --end 필요")

    from turtle.data.krx import KrxFetcher

    fetcher = KrxFetcher()
    frames, all_ev = [], []
    for t in a.tickers:
        df = fetcher.get_ohlcv(t, a.start, a.end)
        if len(df) < 130:
            print(f"[warn] {t}: {len(df)}봉 — 120이평/집계 일부 NaN")
        f = add_features(df)
        anchors = find_anchors(f, a.anchor_pct, a.anchor_vol)
        print(f"{t}: {len(df)}봉, 급등일 {len(anchors)}건 {[str(d.date()) for d in anchors]}")
        if len(anchors):
            all_ev.append(event_rows(f, t, anchors, a.pre))
        frames.append(f.assign(ticker=t))

    if not all_ev:
        print("\n급등일 없음 — --anchor-pct/--anchor-vol 낮춰서 재시도.")
        return 1

    ev = pd.concat(all_ev, ignore_index=True)
    print(f"\n=== 급등일 {ev[['ticker','anchor']].drop_duplicates().shape[0]}건 공통 패턴 "
          f"(offset 0 = 급등일, bool=발생률%, 수치=중앙값) ===")
    print(summarize(ev).to_string())

    d0 = ev[ev.offset == 0]
    print("\n=== 급등일 상세 ===")
    print(d0[["ticker", "date", "chg_pct", "body_ratio", "close_pos",
              "vol_ratio_20", "disparity_20", "adx14", "ma_aligned"]].round(2).to_string(index=False))

    if a.csv:
        ev.to_csv(a.csv, index=False)
        print(f"\n[saved] {a.csv}")
    return 0


def selftest() -> int:
    """합성 데이터로 피처 계산 검증 (네트워크 불필요)."""
    n = 150
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    base = np.linspace(100, 200, n)
    df = pd.DataFrame({"open": base, "high": base * 1.01, "low": base * 0.99,
                       "close": base, "volume": np.full(n, 1000.0)}, index=idx)
    # 마지막 봉: 장대양봉 + 거래량 5배
    df.loc[idx[-1], ["open", "high", "low", "close", "volume"]] = [200, 232, 199, 230, 5000]
    f = add_features(df)
    last = f.iloc[-1]
    assert last["marubozu_bull"], last["body_ratio"]
    assert abs(last["vol_ratio_20"] - 5000 / f["vol"].iloc[-20:].mean()) < 1e-9
    assert last["ma_aligned"], "상승추세면 정배열"
    assert not last["doji"] and not last["hammer"]
    assert last["chg_pct"] > 14
    an = find_anchors(f, pct=8, vol_x=2)
    assert list(an) == [idx[-1]], an
    ev = event_rows(f, "TEST", an, pre=3)
    assert len(ev) == 4 and set(ev.offset) == {-3, -2, -1, 0}
    s = summarize(ev)
    assert s.loc[0, "marubozu_bull"] == 100.0 and s.loc[-1, "marubozu_bull"] == 0.0
    print("selftest OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
