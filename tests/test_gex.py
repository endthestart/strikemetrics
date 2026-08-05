"""GEX tests, cases (and hand-calculated values) carried over from the source
system's validated suite, plus the new input-validation behavior."""

from decimal import Decimal

import pytest

from strikemetrics import (
    ChainRow,
    GEXProfile,
    InvalidInputError,
    compute_gex,
)
from strikemetrics.gex import PERCENT_MOVE


def _row(strike, option_type, gamma, oi, multiplier=100):
    return ChainRow(strike=strike, option_type=option_type, gamma=gamma,
                    open_interest=oi, multiplier=multiplier)


class TestComputeGEXNormal:
    """3 strikes, known gamma/OI, spot=105.0."""

    def setup_method(self):
        spot = 105.0
        # Per 1% move (the x0.01 is the unit, see strikemetrics.gex):
        # Strike 100: call gamma=0.04, oi=500 → GEX = +0.04*500*100*105²*0.01 = +220,500
        # Strike 105: put  gamma=0.05, oi=400 → GEX = -0.05*400*100*105²*0.01 = -220,500
        # Strike 110: call gamma=0.03, oi=300 → GEX = +0.03*300*100*105²*0.01 =  +99,225
        self.rows = [
            _row(100, 'call', 0.04, 500),
            _row(105, 'put',  0.05, 400),
            _row(110, 'call', 0.03, 300),
        ]
        self.result = compute_gex(self.rows, spot)

    def test_net_gex_is_sum_of_all_per_strike_gex(self):
        spot = 105.0
        expected = (0.04 * 500 - 0.05 * 400 + 0.03 * 300) * 100 * (spot ** 2) * PERCENT_MOVE
        assert abs(self.result.net_gex - expected) < 0.01
        assert self.result.net_gex == pytest.approx(99_225.0)

    def test_call_wall_is_strike_with_highest_positive_gex(self):
        assert self.result.call_wall == pytest.approx(100.0)

    def test_put_wall_is_strike_with_highest_negative_gex(self):
        assert self.result.put_wall == pytest.approx(105.0)

    def test_per_strike_sorted_ascending(self):
        strikes = [e.strike for e in self.result.per_strike]
        assert strikes == sorted(strikes)

    def test_result_is_gex_profile(self):
        assert isinstance(self.result, GEXProfile)


def test_zero_cross_detected_at_cumulative_sign_change():
    spot = 100.0
    # strike 90 call: +0.02*1000*100*10000*0.01 =   +200,000
    # strike 95 put:  -0.06*2000*100*10000*0.01 = -1,200,000 → cumulative flips at 95
    rows = [
        _row(90,  'call', 0.02, 1000),
        _row(95,  'put',  0.06, 2000),
        _row(100, 'call', 0.01, 500),
    ]
    assert compute_gex(rows, spot).zero_cross_strike == pytest.approx(95.0)


class TestComputeGEXEmpty:
    def test_empty_returns_zero_profile(self):
        result = compute_gex([], 100.0)
        assert result.net_gex == 0.0
        assert result.zero_cross_strike is None
        assert result.call_wall is None
        assert result.put_wall is None
        assert result.per_strike == ()


def test_rows_with_unknown_gamma_or_oi_are_skipped_not_zeroed():
    spot = 100.0
    rows = [
        _row(100, 'call', None, 500),    # gamma unknown → skip
        _row(105, 'call', 0.03, None),   # OI unknown → skip
        _row(110, 'call', 0.02, 300),    # valid
    ]
    result = compute_gex(rows, spot)
    expected = 0.02 * 300 * 100 * (100.0 ** 2) * PERCENT_MOVE
    assert abs(result.net_gex - expected) < 0.01
    assert len(result.per_strike) == 1
    assert result.per_strike[0].strike == pytest.approx(110.0)


class TestComputeGEXAllPositive:
    def test_put_wall_none_when_no_negative_gex(self):
        rows = [
            _row(100, 'call', 0.04, 500),
            _row(105, 'call', 0.03, 400),
            _row(110, 'call', 0.02, 300),
        ]
        assert compute_gex(rows, 100.0).put_wall is None

    def test_call_wall_set_when_positive_gex_exists(self):
        rows = [
            _row(100, 'call', 0.04, 500),   # GEX 200,000 per 1% move
            _row(105, 'call', 0.03, 400),   # GEX 120,000 per 1% move
        ]
        assert compute_gex(rows, 100.0).call_wall == pytest.approx(100.0)

    def test_zero_cross_none_when_no_crossing(self):
        rows = [
            _row(100, 'call', 0.04, 500),
            _row(105, 'call', 0.03, 400),
        ]
        assert compute_gex(rows, 100.0).zero_cross_strike is None


def test_nonstandard_multiplier_scales_gex():
    rows = [_row(100, 'call', 0.04, 500, multiplier=10)]
    result = compute_gex(rows, 100.0)
    assert result.net_gex == pytest.approx(0.04 * 500 * 10 * 10000 * PERCENT_MOVE)


def test_decimal_inputs_are_accepted():
    # Rows built straight from Decimal-typed feeds normalize cleanly.
    rows = [ChainRow(strike=Decimal('100'), option_type='CALL',
                     gamma=Decimal('0.04'), open_interest=500)]
    result = compute_gex(rows, 100.0)
    assert result.net_gex == pytest.approx(0.04 * 500 * 100 * 10000 * PERCENT_MOVE)


def test_non_positive_spot_raises():
    with pytest.raises(InvalidInputError):
        compute_gex([_row(100, 'call', 0.04, 500)], 0.0)
    with pytest.raises(InvalidInputError):
        compute_gex([], -5.0)


def test_non_positive_multiplier_rejected_at_construction():
    with pytest.raises(ValueError):
        _row(100, 'call', 0.04, 500, multiplier=0)


def test_gex_is_quoted_per_one_percent_move():
    """The unit, pinned. `gamma x spot²` is dollars of delta per a *100%* move,
    which is not a figure anyone quotes; every published GEX carries the x0.01 that
    turns it into dollars to hedge per 1% move. Without it these numbers read 100x
    larger than anything a reader would compare them against."""
    rows = [_row(100, 'call', 0.04, 500)]
    raw = 0.04 * 500 * 100 * (100.0 ** 2)      # 20,000,000, per 100% move
    assert compute_gex(rows, 100.0).net_gex == pytest.approx(raw * 0.01)
    assert compute_gex(rows, 100.0).net_gex == pytest.approx(200_000.0)


def test_the_scaling_moves_no_ranking_or_sign():
    """Everything derived from GEX is a comparison, so the unit cannot change a
    call wall, a put wall, a flip point, or the sign of the net."""
    rows = [
        _row(95, 'put', 0.05, 800),
        _row(100, 'call', 0.04, 500),
        _row(105, 'call', 0.03, 400),
    ]
    profile = compute_gex(rows, 100.0)
    scaled = [s.gex for s in profile.per_strike]
    unscaled = [s.gex / PERCENT_MOVE for s in profile.per_strike]
    # Same ordering, same signs, only the magnitude differs.
    assert (sorted(range(3), key=lambda i: scaled[i])
            == sorted(range(3), key=lambda i: unscaled[i]))
    assert [s > 0 for s in scaled] == [u > 0 for u in unscaled]
    assert profile.call_wall == pytest.approx(100.0)
    assert profile.put_wall == pytest.approx(95.0)


def test_the_sign_convention_matches_the_paper_that_defined_it():
    """calls +1 / puts -1 encodes "dealers long calls, short puts" — SqueezeMetrics
    *Gamma Exposure* (Dec 2017) assumptions 2 and 3. The arithmetic is unforgiving:
    a long option position has positive gamma and a short one negative, whichever
    right it is. Pinned because the module comment stated the inverse for months
    while the code was correct, and a reader trusting the comment would have
    "fixed" working code.
    """
    call = ChainRow(strike=100, option_type='CALL', gamma=0.05, open_interest=100)
    put = ChainRow(strike=100, option_type='PUT', gamma=0.05, open_interest=100)
    assert compute_gex([call], 100.0).net_gex > 0      # dealers long calls
    assert compute_gex([put], 100.0).net_gex < 0       # dealers short puts
