"""Put/call ratio tests, cases carried over from the source system's suite."""

from decimal import Decimal

import pytest

from strikemetrics import ChainRow, Trade, compute_oi_pcr, compute_volume_pcr, oi_pcr_decimal


def _oi_row(option_type, open_interest):
    return ChainRow(strike=100, option_type=option_type, open_interest=open_interest)


class TestComputeVolumePCR:
    def test_volume_pcr_normal(self):
        # 100 put contracts, 200 call contracts → PCR = 0.5
        trades = [
            Trade('put', 50), Trade('put', 50),
            Trade('call', 100), Trade('call', 100),
        ]
        result = compute_volume_pcr(trades)
        assert result.call_volume == 200
        assert result.put_volume == 100
        assert result.ratio == pytest.approx(0.5)

    def test_zero_call_volume_gives_none_ratio_but_real_totals(self):
        result = compute_volume_pcr([Trade('put', 50), Trade('put', 50)])
        assert result.ratio is None
        assert result.call_volume == 0
        assert result.put_volume == 100

    def test_empty_trades(self):
        result = compute_volume_pcr([])
        assert result.ratio is None
        assert result.call_volume == 0
        assert result.put_volume == 0

    def test_only_calls_gives_zero_ratio(self):
        result = compute_volume_pcr([Trade('call', 200)])
        assert result.ratio == pytest.approx(0.0)
        assert result.put_volume == 0

    def test_option_type_strings_normalize(self):
        result = compute_volume_pcr([Trade('CALL', 100), Trade('Put', 50)])
        assert result.call_volume == 100
        assert result.put_volume == 50


class TestComputeOIPCR:
    def test_oi_pcr_normal(self):
        rows = [_oi_row('call', 10000), _oi_row('put', 5000)]
        result = compute_oi_pcr(rows)
        assert result.call_oi == 10000
        assert result.put_oi == 5000
        assert result.ratio == pytest.approx(0.5)

    def test_zero_call_oi_gives_none_ratio(self):
        result = compute_oi_pcr([_oi_row('put', 5000)])
        assert result.ratio is None
        assert result.call_oi == 0
        assert result.put_oi == 5000

    def test_empty_rows(self):
        result = compute_oi_pcr([])
        assert result.ratio is None
        assert result.call_oi == 0
        assert result.put_oi == 0

    def test_unknown_oi_rows_skipped_not_zeroed(self):
        rows = [
            _oi_row('call', 10000),
            _oi_row('call', None),    # unknown → skipped
            _oi_row('put', 5000),
        ]
        result = compute_oi_pcr(rows)
        assert result.call_oi == 10000
        assert result.put_oi == 5000
        assert result.ratio == pytest.approx(0.5)

    def test_all_unknown_gives_none_ratio(self):
        rows = [_oi_row('call', None), _oi_row('put', None)]
        result = compute_oi_pcr(rows)
        assert result.ratio is None
        assert result.call_oi == 0
        assert result.put_oi == 0


class TestOIPCRDecimal:
    def test_quantizes_to_four_places(self):
        assert oi_pcr_decimal(200, 300) == Decimal('1.5000')

    def test_zero_call_oi_returns_none(self):
        assert oi_pcr_decimal(0, 500) is None

    def test_zero_put_oi_returns_zero(self):
        assert oi_pcr_decimal(200, 0) == Decimal('0.0000')


def test_negative_trade_size_rejected():
    with pytest.raises(ValueError):
        Trade('call', -5)
