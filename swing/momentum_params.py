from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class MomentumScreenerParams:
    """모멘텀 스윙 검색기 파라미터. 기본값은 docs/momentum_screener_spec.md §4와 일치한다.

    §6의 실측 성과는 이 기본값 조합으로 나온 것이다. 개별 값을 바꾸면 성과가
    재현되지 않는다 (§6.6 구현 수용 기준 참조).
    """

    # 급등일 판정 (§2.1)
    spike_vol_x: float = 3.0  # 거래량 / 20일 평균 하한
    spike_chg_min: float = 0.08  # 전일 종가 대비 상승률 하한
    spike_close_pos: float = 0.6  # 종가 위치 하한 (윗꼬리 배제)
    spike_ref_window: int = 20  # 거래량 평균 창

    # 감시목록 (§3.2)
    watch_lookback: int = 60  # 급등 이력 조회 기간(거래일)
    watch_min_spikes: int = 1  # 기간 내 최소 급등 횟수
    cooldown: int = 20  # 동일 종목 재신호 간격(거래일)

    # 유니버스 (§3.1)
    turnover_min: float = 1_000_000_000  # 20일 거래대금 중앙값 하한(원). 10억
    turnover_max: float | None = 8_000_000_000  # 상한(원). 80억. None이면 상한 없음
    min_bars: int = 180  # 최소 보유 봉 수 (MA120 + 60일 롤링 계산)

    # 시장 국면 — 정보성, 검색 조건 아님 (§3.4)
    market_proxy: tuple[str, str] = ("069500", "229200")  # KODEX200, KODEX코스닥150
    market_momentum_window: int = 20

    # 진입/청산 (§3.3)
    hold_days: int = 10  # 15로 올리면 공격적 운용
    stop_pct: float = 25.0  # 진입가 대비 고정 손절폭(%). 재해 방지용
    max_positions: int = 20  # 동시 보유 상한. 10 미만 금지

    @property
    def required_bars(self) -> int:
        """마지막 봉 판정에 필요한 최소 이력 봉 수. min_bars와 동일하게 맞춘다."""
        return self.min_bars


def load_momentum_params(path: str = "config.yaml") -> MomentumScreenerParams:
    """config.yaml의 momentum_screener: 섹션을 읽어 MomentumScreenerParams를 만든다.

    섹션이 없으면 전부 기본값. 모르는 키는 TypeError로 즉시 실패한다(오타 방어).
    market_proxy는 YAML에서 리스트로 오므로 tuple로 변환한다.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    section = dict(raw.get("momentum_screener") or {})
    if "market_proxy" in section:
        section["market_proxy"] = tuple(section["market_proxy"])
    return MomentumScreenerParams(**section)
