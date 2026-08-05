"""Open-interest deltas: day-over-day positioning change, per contract and up.

Open interest prints once daily (morning), so comparing two consecutive
snapshots shows where positions were *actually* opened or closed, the tape
tells you volume, ΔOI tells you commitment. Three aggregation levels:
per-contract, per-expiration, per-underlying.

The absence policy matters most here and is preserved exactly from the source
system: a contract missing from yesterday's snapshot, or a ``None`` OI on
either side, keeps its delta unknown (``None``) and is *counted* as unknown
in aggregates (``unknown_contract_count``, ``data_quality='partial'``), it is
never zero-filled, which would silently bias every net figure toward zero.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from strikemetrics.types import ChainRow, OptionType


@dataclass(frozen=True, slots=True)
class ContractDeltaOI:
    """One contract's day-over-day OI change."""

    strike: float
    expiration: str
    option_type: OptionType
    yesterday_oi: int | None
    today_oi: int | None
    delta_oi: int | None                 # signed: today - yesterday; None if unknown
    volume_to_oi_ratio: float | None     # yesterday volume / yesterday OI
    data_quality: str = 'complete'       # complete | missing_yesterday |
    #                                      unknown_today_oi | unknown_yesterday_oi |
    #                                      unknown_yesterday_volume

    def __post_init__(self) -> None:
        # Normalize so aggregation's identity checks can't be defeated by a
        # caller constructing records with 'call'/'put' strings.
        object.__setattr__(self, 'option_type', OptionType.normalize(self.option_type))


@dataclass(frozen=True, slots=True)
class ExpirationDeltaOI:
    expiration: str
    net_delta_oi: int        # sum of signed deltas (known contracts only)
    abs_delta_oi: int        # sum of |delta|, activity magnitude
    call_delta_oi: int
    put_delta_oi: int
    contract_count: int
    unknown_contract_count: int = 0
    data_quality: str = 'complete'       # complete | partial


@dataclass(frozen=True, slots=True)
class UnderlyingDeltaOI:
    net_call_delta_oi: int
    net_put_delta_oi: int
    net_total_delta_oi: int
    contract_count: int
    unknown_contract_count: int = 0
    data_quality: str = 'complete'       # complete | partial


@dataclass(frozen=True, slots=True)
class DeltaOIResult:
    contracts: tuple[ContractDeltaOI, ...] = ()
    by_expiration: tuple[ExpirationDeltaOI, ...] = ()
    underlying_summary: UnderlyingDeltaOI = field(
        default_factory=lambda: UnderlyingDeltaOI(0, 0, 0, 0)
    )


def _key(row: ChainRow) -> tuple[str, float, OptionType]:
    return (row.expiration_key, row.strike, row.option_type)


def compute_delta_oi(
    today_rows: Iterable[ChainRow],
    yesterday_rows: Iterable[ChainRow],
) -> list[ContractDeltaOI]:
    """Per-contract ΔOI between two (typically consecutive-morning) snapshots.

    Every row must carry an ``expiration`` (contracts are keyed by
    expiration + strike + type); rows without one raise ``ValueError``.
    """
    yesterday_lookup = {_key(row): row for row in yesterday_rows}

    contracts: list[ContractDeltaOI] = []
    for row in today_rows:
        today_oi = row.open_interest
        prev = yesterday_lookup.get(_key(row))

        if prev is None:
            contracts.append(ContractDeltaOI(
                strike=row.strike,
                expiration=row.expiration_key,
                option_type=row.option_type,
                yesterday_oi=None,
                today_oi=today_oi,
                delta_oi=None,
                volume_to_oi_ratio=None,
                data_quality='unknown_today_oi' if today_oi is None else 'missing_yesterday',
            ))
            continue

        yesterday_oi = prev.open_interest
        yesterday_vol = prev.volume
        delta = None
        ratio = None
        quality = 'complete'
        if today_oi is None:
            quality = 'unknown_today_oi'
        elif yesterday_oi is None:
            quality = 'unknown_yesterday_oi'
        else:
            delta = today_oi - yesterday_oi
            if yesterday_oi and yesterday_vol is None:
                quality = 'unknown_yesterday_volume'
            elif yesterday_oi:
                ratio = yesterday_vol / yesterday_oi

        contracts.append(ContractDeltaOI(
            strike=row.strike,
            expiration=row.expiration_key,
            option_type=row.option_type,
            yesterday_oi=yesterday_oi,
            today_oi=today_oi,
            delta_oi=delta,
            volume_to_oi_ratio=ratio,
            data_quality=quality,
        ))

    return contracts


def aggregate_delta_oi(contracts: Iterable[ContractDeltaOI]) -> DeltaOIResult:
    """Roll per-contract deltas up to per-expiration and per-underlying levels."""
    contracts = list(contracts)

    exp_buckets: dict[str, list[ContractDeltaOI]] = defaultdict(list)
    for c in contracts:
        exp_buckets[c.expiration].append(c)

    by_expiration: list[ExpirationDeltaOI] = []
    for exp, bucket in exp_buckets.items():
        known = [c for c in bucket if c.delta_oi is not None]
        unknown_count = len(bucket) - len(known)
        by_expiration.append(ExpirationDeltaOI(
            expiration=exp,
            net_delta_oi=sum(c.delta_oi for c in known),
            abs_delta_oi=sum(abs(c.delta_oi) for c in known),
            call_delta_oi=sum(c.delta_oi for c in known if c.option_type is OptionType.CALL),
            put_delta_oi=sum(c.delta_oi for c in known if c.option_type is OptionType.PUT),
            contract_count=len(bucket),
            unknown_contract_count=unknown_count,
            data_quality='partial' if unknown_count else 'complete',
        ))

    known_all = [c for c in contracts if c.delta_oi is not None]
    unknown_count = len(contracts) - len(known_all)
    net_call = sum(c.delta_oi for c in known_all if c.option_type is OptionType.CALL)
    net_put = sum(c.delta_oi for c in known_all if c.option_type is OptionType.PUT)
    summary = UnderlyingDeltaOI(
        net_call_delta_oi=net_call,
        net_put_delta_oi=net_put,
        net_total_delta_oi=net_call + net_put,
        contract_count=len(contracts),
        unknown_contract_count=unknown_count,
        data_quality='partial' if unknown_count else 'complete',
    )

    return DeltaOIResult(
        contracts=tuple(contracts),
        by_expiration=tuple(by_expiration),
        underlying_summary=summary,
    )
