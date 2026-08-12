from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class SwingParams:
    """스윙 스크리너 파라미터. 기본값은 docs/swing_stratgy.md §8 표와 일치한다.

    전부 미검증 시작점이며 백테스트로 튜닝할 대상이다.
    """

    # 조건1 — 저거래량 횡보
    base_window: int = 30           # 장대양봉 직전 검사 구간(거래일)
    base_long_window: int = 60      # 거래량 비교용 장기창. base_window와 겹치지 않는다
    price_contraction: float = 0.20  # 구간 (고가-저가)/저가 상한
    base_vol_ratio: float = 0.8     # 구간 평균 거래량 / 장기창 평균 거래량 상한
    # 조건2 — 대량 거래 장대양봉
    body_min: float = 0.06          # (종가-시가)/시가 하한
    close_pos: float = 0.7          # 종가 위치 계수 (윗꼬리 배제)
    vol_spike: float = 2.5          # 당일 거래량 / 직전 spike_ref_window 평균 하한
    spike_ref_window: int = 20      # 거래량 기준 평균 창 (장대양봉 당일 제외)
    # 조건3 — 거래량 마른 눌림 지지
    pullback_min: int = 1           # 장대양봉 후 최소 경과 거래일
    pullback_max: int = 10          # 장대양봉 후 최대 경과 거래일
    retrace_max: float = 0.5        # 몸통 되돌림 허용 상한
    pullback_vol_ratio: float = 0.3  # 눌림 평균 거래량 / 장대양봉 거래량 상한
    dist_vol: float = 2.0           # 대량 음봉 판정 거래량 배수
    # 유니버스
    mcap_percentile_cut: float = 50.0        # 시총 하위 컷 백분위 (각 시장)
    liquidity_min_value: float = 1_000_000_000  # 20일 평균 거래대금 하한(원)
    min_price: float = 1000.0                # 최소 종가(원)
    # 알림
    notify_empty: bool = True       # 후보 0개일 때도 발송할지

    @property
    def required_bars(self) -> int:
        """조건1 장기창까지 계산 가능한 최소 봉 수.

        가장 오래된 후보 장대양봉(경과 pullback_max일)의 장기창 시작점이
        데이터 안에 들어와야 한다.
        """
        return self.base_window + self.base_long_window + self.pullback_max + 1


def load_swing_params(path: str = "config.yaml") -> SwingParams:
    """config.yaml의 swing: 섹션을 읽어 SwingParams를 만든다.

    섹션이 없으면 전부 기본값. 모르는 키는 TypeError로 즉시 실패한다(오타 방어).
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return SwingParams(**(raw.get("swing") or {}))
