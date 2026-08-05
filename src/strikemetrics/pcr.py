"""Put/call ratios, volume-based (trade tape) and open-interest-based.

Both are put/call; the ratio is ``None`` when the call side is zero (division
undefined), while the raw side totals are always reported so the caller can
still see the imbalance. All trades count toward volume PCR regardless of
aggressor side, PCR is a volume metric, not a directional one.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from strikemetrics.types import ChainRow, OptionType, Trade


@dataclass(frozen=True, slots=True)
class VolumePCR:
    ratio: float | None      # put volume / call volume; None if call volume == 0
    call_volume: int
    put_volume: int


@dataclass(frozen=True, slots=True)
class OIPCR:
    ratio: float | None      # put OI / call OI; None if call OI == 0
    call_oi: int
    put_oi: int


def compute_volume_pcr(trades: Iterable[Trade]) -> VolumePCR:
    """Sum trade sizes by option type and compute the volume put/call ratio."""
    call_volume = 0
    put_volume = 0
    for trade in trades:
        if trade.option_type is OptionType.CALL:
            call_volume += trade.size
        else:
            put_volume += trade.size
    ratio = put_volume / call_volume if call_volume else None
    return VolumePCR(ratio=ratio, call_volume=call_volume, put_volume=put_volume)


def compute_oi_pcr(rows: Iterable[ChainRow]) -> OIPCR:
    """Sum open interest by option type and compute the OI put/call ratio.

    Rows with unknown (``None``) open interest are skipped. Unknown is not zero.
    """
    call_oi = 0
    put_oi = 0
    for row in rows:
        if row.open_interest is None:
            continue
        if row.is_call:
            call_oi += row.open_interest
        else:
            put_oi += row.open_interest
    ratio = put_oi / call_oi if call_oi else None
    return OIPCR(ratio=ratio, call_oi=call_oi, put_oi=put_oi)


def oi_pcr_decimal(call_oi: int, put_oi: int) -> Decimal | None:
    """Exact OI put/call ratio as a Decimal quantized to 4 places, for callers
    that persist the figure. ``None`` when the call side is zero."""
    if call_oi == 0:
        return None
    return (Decimal(put_oi) / Decimal(call_oi)).quantize(Decimal('0.0001'))
