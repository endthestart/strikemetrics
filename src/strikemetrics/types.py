"""Input records for chain analytics.

Analytics operate on plain, frozen records the caller builds from whatever data
source they have (broker SDK, vendor API, database rows). The package never
fetches data.

Numbers are floats by design: these are *positioning analytics* (gamma exposure,
pain, ratios), not accounting. Anything that settles to cash belongs in an
exact-Decimal domain (e.g. the sibling ``optionstruct`` package), not here.

Absence is explicit: a missing greek or open interest is ``None``, never zero;
zero is a real market value and the two must not be conflated. Compute functions
either skip or flag unknown inputs; they never invent numbers.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

DEFAULT_MULTIPLIER = 100  # standard US equity option (shares per contract)


class OptionType(StrEnum):
    CALL = 'CALL'
    PUT = 'PUT'

    @classmethod
    def normalize(cls, value: 'str | OptionType') -> 'OptionType':
        return cls(str(value).upper())


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[call-overload]


@dataclass(frozen=True, slots=True)
class ChainRow:
    """One option contract's slice of a chain snapshot.

    ``strike`` accepts float/int/str/Decimal and is normalized to float;
    ``option_type`` accepts ``'call'``/``'PUT'``/etc. ``multiplier`` is the
    contract's shares-per-contract (defaults to the standard 100, pass the real
    value for non-standard deliverables, it scales GEX and max-pain exposure).
    ``expiration`` is only required by the analytics that group by expiration
    (open-interest deltas).

    ``settlement`` distinguishes contracts that share an expiration date but
    settle against different prints — e.g. an S&P 500 monthly lists both an
    AM-settled ``SPX`` (against the opening SET) and a PM-settled ``SPXW``
    (against the close) on the same third Friday. Anything defined per
    settlement, max pain above all, must not blend them. Leave it ``None`` when
    the chain has only one settlement style; that is the common case and not the
    mistake this guards against.
    """

    strike: float
    option_type: OptionType
    gamma: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    expiration: date | str | None = None
    multiplier: int = DEFAULT_MULTIPLIER
    settlement: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'strike', float(self.strike))  # accepts Decimal/str
        object.__setattr__(self, 'option_type', OptionType.normalize(self.option_type))
        object.__setattr__(self, 'gamma', _float_or_none(self.gamma))
        object.__setattr__(self, 'open_interest', _int_or_none(self.open_interest))
        object.__setattr__(self, 'volume', _int_or_none(self.volume))
        if int(self.multiplier) <= 0:
            raise ValueError(f'multiplier must be positive, got {self.multiplier}')
        object.__setattr__(self, 'multiplier', int(self.multiplier))

    @property
    def is_call(self) -> bool:
        return self.option_type is OptionType.CALL

    @property
    def expiration_key(self) -> str:
        """Expiration as a stable grouping key (ISO string for dates)."""
        if self.expiration is None:
            raise ValueError(f'row for strike {self.strike} has no expiration')
        if isinstance(self.expiration, date):
            return self.expiration.isoformat()
        return str(self.expiration)

    @property
    def settlement_key(self) -> str | None:
        """The settlement *event* this contract belongs to, or ``None`` if unknown.

        A date alone does not identify a settlement: two products can expire on
        one day and settle against different prints. Grouping by this key rather
        than by ``expiration`` is what keeps them apart.
        """
        if self.expiration is None:
            return None
        if self.settlement is None:
            return self.expiration_key
        return f'{self.expiration_key}/{self.settlement}'


@dataclass(frozen=True, slots=True)
class Trade:
    """One trade-tape record, for volume-based ratios."""

    option_type: OptionType
    size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, 'option_type', OptionType.normalize(self.option_type))
        if int(self.size) < 0:
            raise ValueError(f'trade size must be non-negative, got {self.size}')
        object.__setattr__(self, 'size', int(self.size))


__all__ = ['DEFAULT_MULTIPLIER', 'ChainRow', 'OptionType', 'Trade']
