"""Max-pain tests, cases and hand-calculated values carried over from the
source system's validated suite."""

import pytest

from strikemetrics import ChainRow, MaxPainResult, compute_max_pain
from strikemetrics.errors import InvalidInputError


def _row(strike, option_type, oi, multiplier=100):
    return ChainRow(strike=strike, option_type=option_type,
                    open_interest=oi, multiplier=multiplier)


class TestComputeMaxPainNormal:
    """Known OI values, hand-calculated result.

    Strikes: 100, 105, 110
    Calls: 100@1000, 105@500, 110@200
    Puts:  100@200,  105@500, 110@1000

    S=100: call_loss = 0; put_loss = 5*500*100 + 10*1000*100 = 1,250,000
    S=105: call_loss = 5*1000*100 = 500,000; put_loss = 5*1000*100 = 500,000 → 1,000,000
    S=110: call_loss = 10*1000*100 + 5*500*100 = 1,250,000; put_loss = 0

    S=105 minimizes total loss → max pain = 105.
    """

    def setup_method(self):
        self.rows = [
            _row(100, 'call', 1000),
            _row(105, 'call', 500),
            _row(110, 'call', 200),
            _row(100, 'put',  200),
            _row(105, 'put',  500),
            _row(110, 'put',  1000),
        ]
        self.result = compute_max_pain(self.rows)
        assert self.result is not None

    def test_returns_max_pain_result(self):
        assert isinstance(self.result, MaxPainResult)

    def test_max_pain_strike_and_loss(self):
        assert self.result.max_pain_strike == pytest.approx(105.0)
        assert self.result.total_loss_at_max_pain == pytest.approx(1_000_000.0)

    def test_max_pain_strike_has_lowest_total_loss(self):
        min_loss = min(p.total_loss for p in self.result.per_strike)
        chosen = next(p for p in self.result.per_strike
                      if p.strike == pytest.approx(self.result.max_pain_strike))
        assert chosen.total_loss == pytest.approx(min_loss)

    def test_per_strike_sorted_ascending_and_complete(self):
        strikes = [p.strike for p in self.result.per_strike]
        assert strikes == sorted(strikes)
        assert set(strikes) == {100.0, 105.0, 110.0}

    def test_oi_breakdown_matches_input(self):
        by_strike = {p.strike: p for p in self.result.per_strike}
        assert by_strike[100.0].call_oi == 1000
        assert by_strike[105.0].call_oi == 500
        assert by_strike[110.0].call_oi == 200
        assert by_strike[100.0].put_oi == 200
        assert by_strike[105.0].put_oi == 500
        assert by_strike[110.0].put_oi == 1000


def test_calls_only_max_pain_is_lowest_strike():
    rows = [
        _row(100, 'call', 1000),
        _row(105, 'call', 800),
        _row(110, 'call', 600),
    ]
    result = compute_max_pain(rows)
    assert result is not None
    assert result.max_pain_strike == pytest.approx(100.0)


class TestComputeMaxPainNoData:
    def test_empty_returns_none(self):
        assert compute_max_pain([]) is None

    def test_all_unknown_oi_returns_none(self):
        rows = [_row(100, 'call', None), _row(105, 'put', None)]
        assert compute_max_pain(rows) is None

    def test_all_zero_oi_returns_none(self):
        rows = [_row(100, 'call', 0), _row(105, 'put', 0)]
        assert compute_max_pain(rows) is None


class TestComputeMaxPainSingleStrike:
    def test_single_call_strike_is_max_pain(self):
        result = compute_max_pain([_row(100, 'call', 500)])
        assert result is not None
        assert result.max_pain_strike == pytest.approx(100.0)

    def test_single_put_strike_is_max_pain(self):
        result = compute_max_pain([_row(100, 'put', 500)])
        assert result is not None
        assert result.max_pain_strike == pytest.approx(100.0)


def test_missing_side_defaults_to_zero_oi_in_breakdown():
    result = compute_max_pain([_row(100, 'call', 500)])   # no puts at 100
    assert result is not None
    entry = result.per_strike[0]
    assert entry.call_oi == 500
    assert entry.put_oi == 0
    assert entry.total_loss >= 0


def test_nonstandard_multiplier_scales_loss():
    rows = [
        _row(100, 'call', 100, multiplier=10),
        _row(105, 'put', 100, multiplier=10),
    ]
    result = compute_max_pain(rows)
    assert result is not None
    by_strike = {p.strike: p for p in result.per_strike}
    # at S=105: call_loss = (105-100)*100*10 = 5000; put_loss = 0
    assert by_strike[105.0].total_loss == pytest.approx(5000.0)


def test_mixed_expirations_raise_rather_than_blending():
    """Max pain is a statement about one settlement. A union of expirations has
    none, so the blended figure answers a question about a world where all of them
    settle at once — and it looks entirely plausible, which is the danger. The
    constraint was a docstring warning nothing checked until v0.0.3."""
    rows = [
        ChainRow(strike=100, option_type='CALL', open_interest=500,
                 expiration='2026-09-04'),
        ChainRow(strike=100, option_type='PUT', open_interest=500,
                 expiration='2026-09-18'),
    ]
    with pytest.raises(InvalidInputError, match='one settlement'):
        compute_max_pain(rows)


def test_rows_without_an_expiration_are_not_the_mistake_being_guarded():
    """`expiration` is optional on ChainRow. A caller that never sets it is not
    mixing settlements, it is simply not using the field."""
    rows = [
        ChainRow(strike=100, option_type='CALL', open_interest=500),
        ChainRow(strike=105, option_type='PUT', open_interest=500),
    ]
    assert compute_max_pain(rows) is not None


def test_one_date_two_settlements_raise_rather_than_blending():
    """The trap a date-keyed guard cannot see (v0.0.4).

    Every S&P 500 monthly lists an AM-settled SPX against the opening SET and a
    PM-settled SPXW against the close, on the same third Friday. They are two
    settlement events sharing a calendar date. Grouping on the date alone finds
    one expiration, passes, and blends two different questions into a number that
    answers neither.
    """
    rows = [
        ChainRow(strike=7650, option_type='CALL', open_interest=500,
                 expiration='2026-08-21', settlement='AM'),
        ChainRow(strike=7545, option_type='PUT', open_interest=500,
                 expiration='2026-08-21', settlement='PM'),
    ]
    with pytest.raises(InvalidInputError, match='one settlement'):
        compute_max_pain(rows)
    # And the message has to say why, or the caller reads "one settlement", sees
    # one date, and concludes the guard is broken.
    with pytest.raises(InvalidInputError, match='same monthly'):
        compute_max_pain(rows)


def test_each_settlement_computed_alone_is_accepted():
    """Splitting by settlement is the fix, so it must not itself trip the guard."""
    for style in ('AM', 'PM'):
        rows = [
            ChainRow(strike=7650, option_type='CALL', open_interest=500,
                     expiration='2026-08-21', settlement=style),
            ChainRow(strike=7545, option_type='PUT', open_interest=500,
                     expiration='2026-08-21', settlement=style),
        ]
        assert compute_max_pain(rows) is not None


def test_a_settlement_style_alone_does_not_group_across_dates():
    """`settlement` refines the expiration key, it never replaces it. Two PM
    expirations a month apart are still two settlements."""
    rows = [
        ChainRow(strike=100, option_type='CALL', open_interest=500,
                 expiration='2026-09-04', settlement='PM'),
        ChainRow(strike=100, option_type='PUT', open_interest=500,
                 expiration='2026-09-18', settlement='PM'),
    ]
    with pytest.raises(InvalidInputError, match='one settlement'):
        compute_max_pain(rows)
