import numpy as np
import pandas as pd

from swing.momentum_params import MomentumScreenerParams


def compute_screener_features(df: pd.DataFrame, p: MomentumScreenerParams) -> pd.DataFrame:
    """OHLCV(표준 스키마)에서 검색기 판정용 피처를 만든다 (순수 함수).

    반환 컬럼: spike, spike_count, aligned, turnover_med, halted, watch
    모든 값은 해당 일자까지의 데이터만 사용한다 (룩어헤드 없음).
    docs/momentum_screener_spec.md §2, §5와 정의를 공유한다.
    """
    o, h, l, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))

    # 거래정지 봉: OHLC=0, 거래량=0, 종가만 직전값 유지 (§1)
    halted = (o <= 0) | (v <= 0)

    rng = (h - l).replace(0, np.nan)
    close_pos = (c - l) / rng
    vol_ratio = v / v.rolling(p.spike_ref_window).mean()

    spike = (
        (vol_ratio >= p.spike_vol_x)
        & (c.pct_change() >= p.spike_chg_min)
        & (close_pos >= p.spike_close_pos)
        & ~halted
    ).fillna(False)

    ma = {w: c.rolling(w).mean() for w in (5, 20, 60, 120)}
    aligned = (ma[5] > ma[20]) & (ma[20] > ma[60]) & (ma[60] > ma[120])

    turnover_med = (c * v).rolling(20).median()

    out = pd.DataFrame(
        {
            "spike": spike,
            "spike_count": spike.rolling(p.watch_lookback).sum(),
            "aligned": aligned,
            "turnover_med": turnover_med,
        },
        index=df.index,
    )
    liquid = out["turnover_med"] >= p.turnover_min
    if p.turnover_max is not None:
        liquid &= out["turnover_med"] < p.turnover_max

    out["halted"] = halted
    out["watch"] = (
        (out["spike_count"] >= p.watch_min_spikes)
        & out["aligned"]
        & liquid.fillna(False)
        & ~halted
    )
    return out


def screen(df: pd.DataFrame, p: MomentumScreenerParams) -> bool:
    """마지막 봉이 '신규 편입' 신호인지 판정한다 (순수 함수).

    유니버스 필터(U1·U2)는 compute_screener_features()의 watch에 이미 포함되어 있다
    (§3.2 — 신규 편입 판정에 유동성을 포함하는 정의).

    쿨다운은 포함하지 않는다 — watch가 짧은 기간 내 여러 번 False→True로 전환될 수
    있어(예: 유동성 조건이 경계에서 출렁이는 경우), 이 함수만으로는 쿨다운을 정확히
    반영할 수 없다. 실제 매매 판단에는 이 함수 대신 has_fresh_signal()을 쓴다
    (§10 구현 체크리스트 — 쿨다운 상태 관리).
    """
    if len(df) < p.min_bars:
        return False

    f = compute_screener_features(df, p)
    # 신규 편입: 당일 참, 전일 거짓
    return bool(f["watch"].iloc[-1]) and not bool(f["watch"].iloc[-2])


def latest_accepted_signal(df: pd.DataFrame, p: MomentumScreenerParams) -> pd.Timestamp | None:
    """df 이력 전체에서 쿨다운을 적용한 마지막 신호일을 재계산한다 (순수 함수).

    직전 실행에서 낸 신호를 DB 등에 저장해두지 않고, 매 실행마다 fetch한 이력에서
    다시 복원한다 — 무상태 파이프라인 원칙(기존 swing.pipeline과 동일한 설계).
    df가 감시목록 신규 편입(watch가 False→True로 전환) 이력을 여러 건 갖고 있으면,
    직전 채택된 신호로부터 p.cooldown 거래일 이상 지난 것만 채택한다.
    (docs/momentum_screener_spec.md §3.2, 백테스트의 쿨다운 로직과 동일)
    """
    if len(df) < p.min_bars:
        return None

    f = compute_screener_features(df, p)
    watch = f["watch"].to_numpy()
    new = watch & ~np.concatenate(([False], watch[:-1]))

    last_i = None
    for i in np.flatnonzero(new):
        if last_i is not None and (i - last_i) < p.cooldown:
            continue
        last_i = i
    return df.index[last_i] if last_i is not None else None


def has_fresh_signal(df: pd.DataFrame, p: MomentumScreenerParams) -> bool:
    """오늘이 쿨다운까지 반영한 신규 매수 신호일인지 판정한다 (순수 함수).

    파이프라인은 screen() 대신 이 함수로 최종 진입 여부를 결정해야 한다.
    """
    sig = latest_accepted_signal(df, p)
    return sig is not None and sig == df.index[-1]


def stop_price(entry: float, p: MomentumScreenerParams) -> float:
    """진입가 기준 고정 손절가. 진입 시점에 확정하고 이후 갱신하지 않는다 (§3.3)."""
    return entry * (1 - p.stop_pct / 100)


def market_momentum(fetcher, target: str, p: MomentumScreenerParams) -> float | None:
    """시장 국면 지표: 두 대표 ETF의 N일 수익률 평균(%). 정보성 값이다 (I/O).

    후보 선정에는 쓰지 않는다 (§3.4). 조회 실패 시 None을 반환하며, 호출측은
    리포트에서 "N/A"로 표기하고 후보 출력은 그대로 진행해야 한다 — 참고 지표
    하나 때문에 스크리닝 전체를 실패시키지 않는다.
    """
    lookback = (
        pd.Timestamp(target) - pd.Timedelta(days=p.market_momentum_window * 2 + 30)
    ).strftime("%Y%m%d")

    changes = []
    for ticker in p.market_proxy:
        try:
            close = fetcher.get_ohlcv(ticker, lookback, target)["close"]
        except Exception:  # noqa: BLE001 - 참고 지표, 실패해도 스크리닝은 계속
            return None
        if len(close) <= p.market_momentum_window:
            return None
        changes.append(close.pct_change(p.market_momentum_window).iloc[-1] * 100)

    return float(np.mean(changes))
