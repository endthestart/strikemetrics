"""Strike-wall tests, cases carried over from the source system's suite, plus
the new weights/top_n parameters."""

import pytest

from strikemetrics import (
    ChainRow,
    GEXProfile,
    InvalidInputError,
    StrikeGEX,
    StrikeWallResult,
    WallWeights,
    compute_strike_walls,
)
from strikemetrics.walls import _max_pain_proximity, _normalize


def _gex_profile(per_strike: list[tuple[float, float]]) -> GEXProfile:
    entries = tuple(StrikeGEX(s, g) for s, g in per_strike)
    return GEXProfile(net_gex=sum(g for _, g in per_strike), zero_cross_strike=None,
                      call_wall=None, put_wall=None, per_strike=entries)


def _rows(strikes: list[float], call_oi: list[int], put_oi: list[int]) -> list[ChainRow]:
    rows = []
    for s, c, p in zip(strikes, call_oi, put_oi):
        rows.append(ChainRow(strike=s, option_type='call', open_interest=c))
        rows.append(ChainRow(strike=s, option_type='put', open_interest=p))
    return rows


# ── signal helpers ───────────────────────────────────────────────────────────


def test_normalize_standard():
    assert _normalize([0.0, 1.0, 2.0, 3.0]) == \
        [0.0, pytest.approx(1 / 3), pytest.approx(2 / 3), 1.0]


def test_normalize_uniform_no_div_zero():
    assert _normalize([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]


def test_normalize_single_element():
    assert _normalize([42.0]) == [0.0]


def test_max_pain_proximity_at_max_pain():
    assert _max_pain_proximity(100.0, 100.0, 5.0) == pytest.approx(1.0)


def test_max_pain_proximity_one_step_away():
    assert _max_pain_proximity(105.0, 100.0, 5.0) == pytest.approx(0.5)


# ── compute_strike_walls ─────────────────────────────────────────────────────


def test_top_strike_has_highest_score():
    strikes = [100.0, 150.0, 200.0, 250.0, 300.0]
    call_oi = [5000, 100, 100, 100, 100]
    put_oi = [3000, 100, 100, 100, 100]
    rows = _rows(strikes, call_oi, put_oi)
    gex = _gex_profile([(100.0, 10000.0), (150.0, 100.0), (200.0, 100.0),
                        (250.0, 100.0), (300.0, 100.0)])

    result = compute_strike_walls(rows, gex, 100.0, spot=120.0)

    assert isinstance(result, StrikeWallResult)
    assert len(result.walls) > 0
    assert result.walls[0].strike == pytest.approx(100.0)
    assert result.walls[0].composite_score >= result.walls[-1].composite_score


def test_uniform_oi_no_div_zero():
    strikes = [100.0, 110.0, 120.0, 130.0, 140.0]
    rows = _rows(strikes, [1000] * 5, [1000] * 5)
    gex = _gex_profile([(s, float(i + 1) * 100) for i, s in enumerate(strikes)])

    result = compute_strike_walls(rows, gex, None, spot=115.0)
    for wall in result.walls:
        assert wall.oi_score == pytest.approx(0.0)


def test_no_max_pain_gives_zero_max_pain_scores():
    strikes = [100.0, 110.0, 120.0]
    rows = _rows(strikes, [1000, 500, 200], [800, 400, 100])
    gex = _gex_profile([(s, float(i + 1) * 500) for i, s in enumerate(strikes)])

    result = compute_strike_walls(rows, gex, None, spot=110.0)
    for wall in result.walls:
        assert wall.max_pain_score == pytest.approx(0.0)
    assert result.strike_count == 3


def test_top_5_limit_default():
    strikes = [float(100 + i * 5) for i in range(10)]
    call_oi = [1000 - i * 80 for i in range(10)]
    put_oi = [800 - i * 60 for i in range(10)]
    rows = _rows(strikes, call_oi, put_oi)
    gex = _gex_profile([(s, float(10 - i) * 1000) for i, s in enumerate(strikes)])

    result = compute_strike_walls(rows, gex, strikes[0], spot=130.0)
    assert result.strike_count == 10
    assert len(result.walls) == 5


def test_top_n_parameter():
    strikes = [float(100 + i * 5) for i in range(10)]
    rows = _rows(strikes, [1000 - i * 80 for i in range(10)],
                 [800 - i * 60 for i in range(10)])
    result = compute_strike_walls(rows, None, None, spot=130.0, top_n=3)
    assert len(result.walls) == 3


def test_empty_rows_returns_empty_result():
    result = compute_strike_walls([], None, None, spot=100.0)
    assert result.walls == ()
    assert result.strike_count == 0


def test_wall_type_classification():
    strikes = [90.0, 100.0, 110.0]
    rows = _rows(strikes, [1000] * 3, [1000] * 3)
    gex = _gex_profile([(s, 1000.0) for s in strikes])

    result = compute_strike_walls(rows, gex, 100.0, spot=100.0)
    types_by_strike = {w.strike: w.wall_type for w in result.walls}
    assert types_by_strike[90.0] == 'support'
    assert types_by_strike[100.0] == 'pivot'
    assert types_by_strike[110.0] == 'resistance'


def test_custom_weights_change_ranking():
    # Strike 100 dominates on OI; strike 120 dominates on GEX. Putting all the
    # weight on one signal must put that signal's winner first.
    strikes = [100.0, 110.0, 120.0]
    rows = _rows(strikes, [5000, 100, 100], [3000, 100, 100])
    gex = _gex_profile([(100.0, 10.0), (110.0, 20.0), (120.0, 99999.0)])

    oi_only = compute_strike_walls(
        rows, gex, None, spot=110.0,
        weights=WallWeights(oi=1.0, gex=0.0, pcr=0.0, max_pain=0.0),
    )
    assert oi_only.walls[0].strike == pytest.approx(100.0)

    gex_only = compute_strike_walls(
        rows, gex, None, spot=110.0,
        weights=WallWeights(oi=0.0, gex=1.0, pcr=0.0, max_pain=0.0),
    )
    assert gex_only.walls[0].strike == pytest.approx(120.0)


def test_invalid_spot_and_top_n_raise():
    rows = _rows([100.0], [10], [10])
    with pytest.raises(InvalidInputError):
        compute_strike_walls(rows, None, None, spot=0.0)
    with pytest.raises(InvalidInputError):
        compute_strike_walls(rows, None, None, spot=100.0, top_n=0)


# ── the pcr signal's scale ───────────────────────────────────────────────────


def test_a_call_less_strike_does_not_flatten_every_real_ratio():
    """The regression. A pure-put strike used to contribute its open-interest
    *count* into a vector of *ratios*; min-max normalization then crushed every
    genuine reading to ~0.0001, leaving pcr, a fifth of the composite score, as a
    one-hot flag for "no calls here".

    Observed before the fix, on exactly these rows:
        5900 -> 1.0000   (30,000 puts, no calls)
        6000 -> 0.0001   (ratio 5.0, a genuinely put-heavy strike)
        6100 -> 0.0000   (ratio 2.0)
    """
    rows = [
        ChainRow(strike=5900, option_type='put', open_interest=30_000),
        ChainRow(strike=6000, option_type='put', open_interest=25_000),
        ChainRow(strike=6000, option_type='call', open_interest=5_000),    # ratio 5.0
        ChainRow(strike=6100, option_type='put', open_interest=20_000),
        ChainRow(strike=6100, option_type='call', open_interest=10_000),   # ratio 2.0
    ]
    by_strike = {w.strike: w for w in
                 compute_strike_walls(rows, None, None, spot=6050.0, top_n=5).walls}

    # The call-less strike still ranks top, it is the most put-skewed thing here.
    assert by_strike[5900.0].pcr_score == pytest.approx(1.0)
    # And the 5.0-ratio strike is no longer indistinguishable from the 2.0 one.
    assert by_strike[6000.0].pcr_score == pytest.approx(1.0)
    assert by_strike[6100.0].pcr_score == pytest.approx(0.0)
    assert by_strike[6000.0].pcr_score > by_strike[6100.0].pcr_score


def test_a_call_less_strike_ties_with_the_most_skewed_measurable_strike():
    """It takes the ceiling, not something above it. An undefined ratio is maximal
    imbalance, but inventing a magnitude for it would re-create the original bug in
    a smaller form."""
    rows = [
        ChainRow(strike=100, option_type='put', open_interest=900),        # no calls
        ChainRow(strike=105, option_type='put', open_interest=800),
        ChainRow(strike=105, option_type='call', open_interest=100),       # ratio 8.0
        ChainRow(strike=110, option_type='put', open_interest=100),
        ChainRow(strike=110, option_type='call', open_interest=100),       # ratio 1.0
    ]
    by_strike = {w.strike: w for w in
                 compute_strike_walls(rows, None, None, spot=105.0, top_n=5).walls}
    assert by_strike[100.0].pcr_score == by_strike[105.0].pcr_score


def test_a_chain_with_no_calls_at_all_distinguishes_nobody_by_pcr():
    """Every strike is call-less, so no strike is *more* put-skewed than another by
    a measure none of them can express. A uniform vector normalizes to zeros , 
    the signal abstains rather than inventing an order from open-interest size."""
    rows = [ChainRow(strike=k, option_type='put', open_interest=oi)
            for k, oi in [(100, 500), (105, 9_000), (110, 200)]]
    walls = compute_strike_walls(rows, None, None, spot=105.0, top_n=5).walls
    assert {w.pcr_score for w in walls} == {0.0}


def test_default_weights_do_not_double_count_open_interest():
    """GEX is `gamma x OI x multiplier x spot²`, so on a liquid chain it largely
    restates open interest. Weighting the two as independent signals would spend
    most of the blend ranking strikes by size twice, which is why `gex` carries
    less weight than `oi` and less than either genuinely independent signal."""
    w = WallWeights()
    assert w.gex < w.oi
    assert w.gex < w.pcr and w.gex < w.max_pain
    # The two signals that carry information the others do not hold half the blend.
    assert w.pcr + w.max_pain == pytest.approx(0.5)
    assert w.oi + w.gex + w.pcr + w.max_pain == pytest.approx(1.0)
