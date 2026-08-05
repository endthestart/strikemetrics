"""Open-interest delta tests, cases carried over from the source system's
suite. The load-bearing property: unknown stays unknown, never zero-filled."""

from decimal import Decimal

import pytest

from strikemetrics import (
    ChainRow,
    ContractDeltaOI,
    DeltaOIResult,
    OptionType,
    aggregate_delta_oi,
    compute_delta_oi,
)

EXP = '2026-04-18'


def _row(expiration, strike, option_type, open_interest, volume=None):
    return ChainRow(strike=Decimal(str(strike)), option_type=option_type,
                    open_interest=open_interest, volume=volume,
                    expiration=expiration)


class TestComputeDeltaOI:
    def test_basic_delta_computation(self):
        today = [
            _row(EXP, 100, 'call', 1500),
            _row(EXP, 105, 'call', 800),
            _row(EXP, 100, 'put', 2200),
        ]
        yesterday = [
            _row(EXP, 100, 'call', 1200),
            _row(EXP, 105, 'call', 900),
            _row(EXP, 100, 'put', 2000),
        ]
        contracts = compute_delta_oi(today, yesterday)

        assert len(contracts) == 3
        by_key = {(c.expiration, c.strike, c.option_type): c for c in contracts}

        c100c = by_key[(EXP, 100.0, OptionType.CALL)]
        assert c100c.yesterday_oi == 1200
        assert c100c.today_oi == 1500
        assert c100c.delta_oi == 300
        assert by_key[(EXP, 105.0, OptionType.CALL)].delta_oi == -100
        assert by_key[(EXP, 100.0, OptionType.PUT)].delta_oi == 200

    def test_missing_prior_day_contract_stays_unknown(self):
        contracts = compute_delta_oi([_row(EXP, 110, 'call', 500)], [])
        c = contracts[0]
        assert c.yesterday_oi is None
        assert c.today_oi == 500
        assert c.delta_oi is None
        assert c.data_quality == 'missing_yesterday'

    def test_volume_to_oi_ratio(self):
        # yesterday volume=500, yesterday OI=200 → ratio=2.5
        contracts = compute_delta_oi(
            [_row(EXP, 100, 'call', 300)],
            [_row(EXP, 100, 'call', 200, volume=500)],
        )
        assert contracts[0].volume_to_oi_ratio == pytest.approx(2.5)

    def test_ratio_none_without_yesterday_row(self):
        contracts = compute_delta_oi([_row(EXP, 100, 'call', 500)], [])
        assert contracts[0].volume_to_oi_ratio is None

    def test_unknown_today_oi_stays_unknown(self):
        contracts = compute_delta_oi(
            [_row(EXP, 100, 'call', None)],
            [_row(EXP, 100, 'call', 200, volume=500)],
        )
        assert contracts[0].today_oi is None
        assert contracts[0].delta_oi is None
        assert contracts[0].data_quality == 'unknown_today_oi'

    def test_unknown_yesterday_oi_stays_unknown(self):
        contracts = compute_delta_oi(
            [_row(EXP, 100, 'call', 300)],
            [_row(EXP, 100, 'call', None, volume=500)],
        )
        assert contracts[0].yesterday_oi is None
        assert contracts[0].delta_oi is None
        assert contracts[0].data_quality == 'unknown_yesterday_oi'

    def test_unknown_yesterday_volume_keeps_ratio_unknown(self):
        contracts = compute_delta_oi(
            [_row(EXP, 100, 'call', 300)],
            [_row(EXP, 100, 'call', 200, volume=None)],
        )
        assert contracts[0].delta_oi == 100
        assert contracts[0].volume_to_oi_ratio is None
        assert contracts[0].data_quality == 'unknown_yesterday_volume'

    def test_empty_today_rows_returns_empty_list(self):
        assert compute_delta_oi([], [_row(EXP, 100, 'call', 1000)]) == []

    def test_row_without_expiration_raises(self):
        with pytest.raises(ValueError, match='expiration'):
            compute_delta_oi(
                [ChainRow(strike=100, option_type='call', open_interest=500)], []
            )

    def test_date_and_string_expirations_key_identically(self):
        from datetime import date

        contracts = compute_delta_oi(
            [_row(date(2026, 4, 18), 100, 'call', 1500)],
            [_row('2026-04-18', 100, 'call', 1200)],
        )
        assert contracts[0].delta_oi == 300     # matched across representations


class TestAggregateDeltaOI:
    def _contract(self, expiration, strike, option_type, delta_oi):
        return ContractDeltaOI(
            strike=strike, expiration=expiration, option_type=option_type,
            yesterday_oi=1000, today_oi=1000 + delta_oi, delta_oi=delta_oi,
            volume_to_oi_ratio=None,
        )

    def test_per_expiration_aggregation(self):
        exp2 = '2026-05-16'
        contracts = [
            self._contract(EXP, 100.0, 'call', 300),
            self._contract(EXP, 100.0, 'put', -150),
            self._contract(exp2, 105.0, 'call', 200),
            self._contract(exp2, 105.0, 'put', 100),
        ]
        result = aggregate_delta_oi(contracts)
        by_exp = {e.expiration: e for e in result.by_expiration}

        e1 = by_exp[EXP]
        assert e1.net_delta_oi == 150       # 300 + (-150)
        assert e1.abs_delta_oi == 450       # |300| + |-150|
        assert e1.call_delta_oi == 300
        assert e1.put_delta_oi == -150
        assert e1.contract_count == 2

        e2 = by_exp[exp2]
        assert e2.net_delta_oi == 300
        assert e2.abs_delta_oi == 300

    def test_per_underlying_aggregation(self):
        contracts = [
            self._contract(EXP, 100.0, 'call', 500),
            self._contract(EXP, 105.0, 'call', 200),
            self._contract(EXP, 100.0, 'put', -300),
            self._contract(EXP, 100.0, 'put', 100),
        ]
        summary = aggregate_delta_oi(contracts).underlying_summary
        assert summary.net_call_delta_oi == 700
        assert summary.net_put_delta_oi == -200
        assert summary.net_total_delta_oi == 500
        assert summary.contract_count == 4

    def test_result_contains_all_levels(self):
        result = aggregate_delta_oi([self._contract(EXP, 100.0, 'call', 100)])
        assert isinstance(result, DeltaOIResult)
        assert len(result.contracts) == 1
        assert len(result.by_expiration) == 1
        assert result.underlying_summary is not None

    def test_unknown_contracts_are_counted_not_zero_filled(self):
        contracts = [
            self._contract(EXP, 100.0, 'call', 100),
            ContractDeltaOI(
                strike=105.0, expiration=EXP, option_type='call',
                yesterday_oi=None, today_oi=500, delta_oi=None,
                volume_to_oi_ratio=None, data_quality='missing_yesterday',
            ),
        ]
        result = aggregate_delta_oi(contracts)
        assert result.by_expiration[0].net_delta_oi == 100
        assert result.by_expiration[0].unknown_contract_count == 1
        assert result.by_expiration[0].data_quality == 'partial'
        assert result.underlying_summary.net_total_delta_oi == 100
        assert result.underlying_summary.unknown_contract_count == 1
        assert result.underlying_summary.data_quality == 'partial'
