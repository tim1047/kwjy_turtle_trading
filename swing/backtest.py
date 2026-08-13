"""장대양봉 종가베팅(A안) vs 눌림목 진입(B안) 비교 백테스트.

두 방식은 같은 장대양봉·같은 손절선(장대양봉 저가)을 쓰고 진입 시점만 다르다.
따라서 R = (청산가 - 진입가) / (진입가 - 손절가) 로 비교하면 손절폭 차이가
자동으로 반영된다. 승률이 아니라 이 R의 기대값이 판단 기준이다.

사용법:
    # 단일 종목 — 조회 1콜, 즉시. 거래 내역까지 출력한다
    python -m swing.backtest --ticker 005930 --start 20220101 --end 20260812

    # 유니버스 전체 — 1회차만 수집 ~15분, 이후 db/bt_cache 재사용
    python -m swing.backtest --all --start 20220101 --end 20260812
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # pykrx가 임포트 시점에 KRX_ID/KRX_PW를 읽으므로 그 전에 채운다

from swing.params import SwingParams, load_swing_params
from swing.screener import _pole_ok, _pullback_ok, avg_turnover_20
from swing.universe import build_swing_universe
from turtle.calendar import lookback_start
from turtle.data.krx import KrxFetcher
from turtle.indicators import atr_wilder, rolling_high, true_range

log = logging.getLogger(__name__)

CACHE_DIR = Path("db/bt_cache")

# 구간 첫날의 장대양봉도 판정하려면 박스창·거래량창(최대 30봉)이 앞에 있어야 한다.
# 달력일 180이면 연휴를 최대로 잡아도 여유가 있다.
_WARMUP_DAYS = 180


# --------------------------------------------------------------------------
# 1단계: 데이터 수집 (네트워크. 1회만)
# --------------------------------------------------------------------------

def fetch_all(start: str, end: str, p: SwingParams) -> None:
    """유니버스 전 종목의 수정주가를 받아 db/bt_cache/에 저장한다 (I/O).

    유니버스는 end 시점 단면으로 확정한다 -> 그 사이 상장폐지·시총 하락으로
    빠진 종목이 표본에서 누락되는 생존편향이 있다. 결과를 낙관적으로 보정해서
    읽어야 한다 (특히 손절 쪽이 과소평가된다).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    universe = build_swing_universe(end, p)
    fetcher = KrxFetcher()
    log.info("유니버스 %d종목 수집 시작 (~%.0f분)", len(universe), len(universe) * 0.5 / 60)

    for i, (ticker, _name, _market, _mcap) in enumerate(universe, 1):
        path = CACHE_DIR / f"{ticker}.pkl"
        if path.exists():
            continue
        try:
            df = fetcher.get_ohlcv(ticker, start, end)
            if len(df) >= p.required_bars:
                df.to_pickle(path)
        except Exception as exc:  # noqa: BLE001 - 종목 실패가 수집을 막지 않도록
            log.warning("수집 실패 %s: %s", ticker, exc)
        if i % 100 == 0:
            log.info("  %d/%d", i, len(universe))


def load_cached() -> dict[str, pd.DataFrame]:
    """캐시된 종목별 OHLCV를 전부 읽는다 (I/O)."""
    return {f.stem: pd.read_pickle(f) for f in sorted(CACHE_DIR.glob("*.pkl"))}


# --------------------------------------------------------------------------
# 2단계: 이벤트 추출 + 청산 시뮬 (순수 함수)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BtTrade:
    ticker: str
    arm: str  # "A"(종가베팅) 또는 "B"(눌림목)
    pole_date: str
    entry_date: str
    exit_date: str
    entry: float
    stop: float
    exit_price: float
    elapsed: int  # 장대양봉 이후 진입까지 경과 거래일 (A안은 0)
    bars_held: int
    reason: str  # "STOP" | "TIMEOUT"

    @property
    def risk_pct(self) -> float:
        """진입가 대비 손절폭(%). A안이 B안보다 구조적으로 크다."""
        return (self.entry - self.stop) / self.entry * 100.0

    @property
    def pnl_pct(self) -> float:
        """진입가 대비 최종 수익률(%). 레버리지·분할 없이 1회 진입 기준."""
        return (self.exit_price - self.entry) / self.entry * 100.0

    @property
    def r(self) -> float:
        """손익을 손절폭 배수로 환산한 값. 두 방식의 유일한 공정 비교 단위.

        pnl_pct는 손절폭이 다르면 그대로 비교할 수 없다 (손절 20%짜리의 +10%와
        손절 5%짜리의 +10%는 감수한 위험이 4배 차이난다). 그래서 판단은 R로 하고
        pnl_pct는 체감용으로 같이 표시한다.
        """
        return (self.exit_price - self.entry) / (self.entry - self.stop)


def chandelier_series(df: pd.DataFrame) -> pd.Series:
    """바별 샹들리에 손절 후보값 (22일 고가 - 3*ATR20) (순수 함수).

    turtle.indicators.chandelier_level과 같은 식이되 전 구간을 한 번에 계산한다
    (봉마다 compute_indicators를 다시 부르면 ATR을 매번 처음부터 재계산한다).

    j시점 값은 j 이후 봉을 보지 않는다. 고가 항은 rolling_high의 shift(1) 때문에
    j-1까지만, ATR 항은 당일 TR까지 포함한다. 청산 판정을 종가에 내리므로 당일
    봉은 이미 알고 있는 정보다 (turtle/backtest.py도 같은 규약).
    """
    return rolling_high(df["high"], 22) - 3 * atr_wilder(true_range(df), 20)


def simulate_exit(
    df: pd.DataFrame,
    entry_idx: int,
    stop: float,
    max_hold: int,
    trail: pd.Series | None = None,
) -> tuple[int, float, str]:
    """진입 다음 봉부터 청산 조건이 걸릴 때까지 추적한다 (순수 함수).

    반환: (청산 봉 인덱스, 청산가, 사유). 사유는 STOP / TRAIL / TIMEOUT.

    - STOP: 장중 저가가 손절선을 건드리면 체결. 갭하락으로 시가가 이미 손절선
      아래면 시가 체결로 잡는다 (손절가 체결로 가정하면 갭 손실이 통째로
      사라져 결과가 낙관 편향된다). 한 봉에서 둘 다 걸리면 STOP 우선 — 더 낮은
      가격이라 보수적이다.
    - TRAIL: trail이 주어지면 샹들리에 손절을 ratchet하며 종가 이탈 시 청산.
      turtle 본체와 동일하게 종가 기준이다.
    - TIMEOUT: 위 둘 다 안 걸리면 max_hold번째 봉 종가.
    """
    last = min(entry_idx + max_hold, len(df) - 1)
    # 인자 순서 max(prior, candidate)가 중요하다: candidate가 NaN(지표 워밍업
    # 부족)이면 비교가 False라 prior가 유지된다. 뒤집으면 NaN이 전파돼 그때까지
    # 올려둔 손절선을 잃는다 (turtle/stoploss.py에 같은 주석).
    level = float("-inf")
    if trail is not None:
        level = max(level, float(trail.iloc[entry_idx]))

    for j in range(entry_idx + 1, last + 1):
        if float(df["low"].iloc[j]) <= stop:
            return j, min(float(df["open"].iloc[j]), stop), "STOP"
        if trail is not None:
            level = max(level, float(trail.iloc[j]))
            close_j = float(df["close"].iloc[j])
            if close_j <= level:  # level이 -inf/NaN이면 항상 False
                return j, close_j, "TRAIL"
    return last, float(df["close"].iloc[last]), "TIMEOUT"


def extract_trades(
    ticker: str,
    df: pd.DataFrame,
    p: SwingParams,
    max_hold: int,
    stop_mode: str = "pole",
    exit_mode: str = "trail",
) -> list[BtTrade]:
    """한 종목의 전 구간에서 A안/B안 거래를 뽑는다 (순수 함수).

    장대양봉 d를 먼저 전부 찾고, 그 d 하나마다 A안 1건 + (눌림 조건을 처음
    만족하는 날이 있으면) B안 1건을 만든다. 같은 d를 공유하므로 짝비교가 된다.
    같은 d가 최대 pullback_max일 연속으로 알림에 뜨는 실운용과 달리, 백테스트는
    첫 히트만 잡는다 (같은 사건을 10번 세면 표본이 부풀려진다).

    stop_mode:
      "pole"     — 양쪽 다 장대양봉 저가. 스펙 §11 규칙이고 손절선이 같아
                   진입가 차이만 R에 반영된다. 다만 눌림이 장대양봉 종가 위에서
                   일어나면 B안 진입가가 더 높아 손절폭이 오히려 커진다.
      "pullback" — B안만 눌림 구간 저가로 조인다(A안은 진입 시점에 눌림 자체가
                   없어 대안이 없다). 각 방식의 실전 손절 위치를 쓰는 비교.

    exit_mode:
      "trail" — 샹들리에 트레일링으로 익절. A/B 양쪽에 동일 적용.
      "hold"  — 트레일링 없이 max_hold일 홀딩. 청산 규칙의 영향을 배제하고
                진입 시점만 비교하고 싶을 때.
    """
    n = len(df)
    need = max(p.base_window, p.spike_ref_window)
    trail = chandelier_series(df) if exit_mode == "trail" else None
    out: list[BtTrade] = []

    for d in range(need, n - 1):
        if not _pole_ok(df, d, p):
            continue
        stop = float(df["low"].iloc[d])
        pole_date = df.index[d].strftime("%Y-%m-%d")

        # A안 — 장대양봉 당일 종가에 진입
        entry_a = float(df["close"].iloc[d])
        if entry_a > stop:
            j, px, reason = simulate_exit(df, d, stop, max_hold, trail)
            out.append(BtTrade(
                ticker=ticker, arm="A", pole_date=pole_date,
                entry_date=pole_date, exit_date=df.index[j].strftime("%Y-%m-%d"),
                entry=entry_a, stop=stop, exit_price=px,
                elapsed=0, bars_held=j - d, reason=reason,
            ))

        # B안 — 눌림 조건을 처음 만족한 날 종가에 진입
        for k in range(p.pullback_min, p.pullback_max + 1):
            t = d + k
            if t >= n:
                break
            if not _pullback_ok(df.iloc[: t + 1], d, p):
                continue
            entry_b = float(df["close"].iloc[t])
            stop_b = stop
            if stop_mode == "pullback":
                stop_b = max(stop, float(df["low"].iloc[d + 1 : t + 1].min()))
            if entry_b > stop_b:
                j, px, reason = simulate_exit(df, t, stop_b, max_hold, trail)
                out.append(BtTrade(
                    ticker=ticker, arm="B", pole_date=pole_date,
                    entry_date=df.index[t].strftime("%Y-%m-%d"),
                    exit_date=df.index[j].strftime("%Y-%m-%d"),
                    entry=entry_b, stop=stop_b, exit_price=px,
                    elapsed=k, bars_held=j - t, reason=reason,
                ))
            break  # 첫 히트만

    return out


def summarize(trades: list[BtTrade]) -> dict[str, float]:
    """R 기준 요약 지표 (순수 함수). 기대값 = 평균 R 이 최종 판단 기준."""
    if not trades:
        return {"n": 0}
    rs = sorted(t.r for t in trades)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    pnls = sorted(t.pnl_pct for t in trades)
    win_pnls = [x for x in pnls if x > 0]
    loss_pnls = [x for x in pnls if x <= 0]
    return {
        "n": len(rs),
        "win_rate": len(wins) / len(rs) * 100.0,
        "avg_r": sum(rs) / len(rs),
        "median_r": rs[len(rs) // 2],
        "avg_win_r": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss_r": sum(losses) / len(losses) if losses else 0.0,
        "avg_pnl_pct": sum(pnls) / len(pnls),
        "median_pnl_pct": pnls[len(pnls) // 2],
        "avg_win_pnl_pct": sum(win_pnls) / len(win_pnls) if win_pnls else 0.0,
        "avg_loss_pnl_pct": sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0,
        "best_pnl_pct": pnls[-1],
        "worst_pnl_pct": pnls[0],
        "avg_risk_pct": sum(t.risk_pct for t in trades) / len(trades),
        "avg_bars_held": sum(t.bars_held for t in trades) / len(trades),
        "stop_rate": sum(t.reason == "STOP" for t in trades) / len(rs) * 100.0,
        "trail_rate": sum(t.reason == "TRAIL" for t in trades) / len(rs) * 100.0,
        "timeout_rate": sum(t.reason == "TIMEOUT" for t in trades) / len(rs) * 100.0,
    }


def format_trades(trades: list[BtTrade]) -> str:
    """거래 내역 표 (순수 함수). 같은 장대양봉의 A/B가 나란히 오도록 정렬한다.

    단일 종목 백테스트에서 차트와 대조하며 눈으로 검증하기 위한 출력이다.
    """
    if not trades:
        return "조건을 만족하는 장대양봉 없음"
    # 한글 헤더는 터미널에서 2칸을 먹어 f-string 폭 계산과 어긋난다. 헤더도
    # 데이터도 ASCII 폭으로 맞추고 컬럼은 구분자로 띄운다.
    head = (
        f"{'code':<8}{'arm':<4}{'pole':<12}{'entry':<12}{'price':>10}{'stop':>10}"
        f"{'risk':>8}  {'exit':<12}{'px':>10}{'pnl':>9}{'R':>8}  why"
    )
    lines = [
        "  pole=장대양봉일  entry=진입일  risk=손절폭  pnl=수익률  R=손절폭 배수 손익",
        "",
        head,
        "-" * len(head),
    ]
    for t in sorted(trades, key=lambda t: (t.ticker, t.pole_date, t.arm)):
        lines.append(
            f"{t.ticker:<8}{t.arm:<4}{t.pole_date:<12}{t.entry_date:<12}{t.entry:>10,.0f}"
            f"{t.stop:>10,.0f}{t.risk_pct:>7.1f}%  {t.exit_date:<12}"
            f"{t.exit_price:>10,.0f}{t.pnl_pct:>+8.1f}%{t.r:>8.2f}  {t.reason}"
        )
    return "\n".join(lines)


def format_report(by_arm: dict[str, dict[str, float]], max_hold: int) -> str:
    """A/B 요약을 나란히 놓은 텍스트 리포트 (순수 함수)."""
    label = {"A": "A안 종가베팅", "B": "B안 눌림목"}
    rows = [
        ("표본 수", "n", "{:.0f}"),
        ("승률(%)", "win_rate", "{:.1f}"),
        ("평균 수익률(%)", "avg_pnl_pct", "{:+.2f}"),
        ("중앙값 수익률(%)", "median_pnl_pct", "{:+.2f}"),
        ("평균 이익(%)", "avg_win_pnl_pct", "{:+.2f}"),
        ("평균 손실(%)", "avg_loss_pnl_pct", "{:+.2f}"),
        ("최대 이익(%)", "best_pnl_pct", "{:+.2f}"),
        ("최대 손실(%)", "worst_pnl_pct", "{:+.2f}"),
        ("평균 손절폭(%)", "avg_risk_pct", "{:.2f}"),
        ("평균 보유(거래일)", "avg_bars_held", "{:.1f}"),
        ("STOP 청산(%)", "stop_rate", "{:.1f}"),
        ("TRAIL 청산(%)", "trail_rate", "{:.1f}"),
        ("TIMEOUT 청산(%)", "timeout_rate", "{:.1f}"),
        ("평균 R (기대값)", "avg_r", "{:+.3f}"),
        ("중앙값 R", "median_r", "{:+.3f}"),
        ("평균 이익 R", "avg_win_r", "{:+.2f}"),
        ("평균 손실 R", "avg_loss_r", "{:+.2f}"),
    ]
    lines = [f"장대양봉 진입 시점 비교 백테스트 (보유 최대 {max_hold}거래일)", ""]
    lines.append(f"{'지표':<18}{label['A']:>16}{label['B']:>16}")
    lines.append("-" * 50)
    for name, key, fmt in rows:
        cells = [fmt.format(by_arm[a].get(key, 0)) for a in ("A", "B")]
        lines.append(f"{name:<18}{cells[0]:>16}{cells[1]:>16}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--ticker",
        help="종목 코드. 쉼표로 여러 개 (예: 042700,247540). 종목당 조회 1콜, 캐시 미사용",
    )
    src.add_argument("--all", action="store_true", help="유니버스 전체 (db/bt_cache 수집·재사용)")
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument("--hold", type=int, default=20, help="최대 보유 거래일(상한)")
    parser.add_argument(
        "--exit", choices=["trail", "hold"], default="trail", dest="exit_mode",
        help="익절 방식. trail=샹들리에 트레일링(기본), hold=익절 없이 --hold일 홀딩",
    )
    parser.add_argument(
        "--stop", choices=["pole", "pullback"], default="pole",
        help="B안 손절 위치. pole=장대양봉 저가(스펙 §11), pullback=눌림 구간 저가",
    )
    parser.add_argument("--csv", help="개별 거래를 이 경로에 CSV로 저장")
    args = parser.parse_args()

    p = load_swing_params()
    # 구간 첫날부터 판정 가능하도록 워밍업만큼 앞서 조회하고, 진입일이 start
    # 이전인 거래는 뒤에서 버린다. 워밍업 없이 start부터 받으면 앞 30여 거래일이
    # 조용히 사라진다.
    warmup = lookback_start(args.start, days=_WARMUP_DAYS)

    if args.ticker:
        fetcher = KrxFetcher()
        tickers = [t.strip() for t in args.ticker.split(",") if t.strip()]
        frames = {t: fetcher.get_ohlcv(t, warmup, args.end) for t in tickers}
    else:
        fetch_all(warmup, args.end, p)
        frames = load_cached()
        if not frames:
            raise SystemExit(f"{CACHE_DIR}가 비어 있음 — 수집 실패")

    trades: list[BtTrade] = []
    for ticker, df in frames.items():
        if len(df) < p.required_bars:
            log.warning("%s 히스토리 부족 (%d봉 < %d)", ticker, len(df), p.required_bars)
            continue
        # 유동성 필터는 유니버스 스캔에만 적용한다. 단일 종목은 사용자가 직접
        # 지정한 것이므로 걸러내지 않는다.
        if not args.ticker and avg_turnover_20(df) < p.liquidity_min_value:
            continue
        trades.extend(extract_trades(ticker, df, p, args.hold, args.stop, args.exit_mode))

    start_iso = datetime.strptime(args.start, "%Y%m%d").strftime("%Y-%m-%d")
    trades = [t for t in trades if t.entry_date >= start_iso]

    if args.ticker:
        print(
            f"{args.ticker}  {args.start}~{args.end}  "
            f"익절={args.exit_mode}  손절={args.stop}\n"
        )
        print(format_trades(trades))
        print()
    by_arm = {a: summarize([t for t in trades if t.arm == a]) for a in ("A", "B")}
    print(format_report(by_arm, args.hold))

    if args.csv:
        pd.DataFrame(
            [vars(t) | {"pnl_pct": t.pnl_pct, "r": t.r, "risk_pct": t.risk_pct} for t in trades]
        ).to_csv(args.csv, index=False)
        print(f"\n개별 거래 {len(trades)}건 -> {args.csv}")


if __name__ == "__main__":
    main()
