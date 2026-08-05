"""Max pain: the expiration price where option buyers collectively lose most.

For each candidate strike S (every strike carrying open interest):

- call loss(S) = sum over call strikes K < S of ``(S - K) x OI(K) x multiplier``
- put loss(S)  = sum over put strikes  K > S of ``(K - S) x OI(K) x multiplier``

Max pain is the S minimizing total loss, the price at which the fewest bought
contracts finish in the money.

**One settlement only, and it is enforced.** Max pain is a statement about a
single settlement — "where would this settle to hurt buyers most". A union has no
settlement, so a blended figure answers a question about a world where everything
settles at once. This used to be a docstring warning that nothing checked, which
is a trap: ``ChainRow`` carries an expiration and summing across them silently
produces a plausible-looking number. Mixed rows now raise.

**A date is not a settlement.** The guard groups on ``settlement_key``, not on
the expiration date, because two products routinely expire on the same day and
settle against different prints. Every S&P 500 monthly lists an AM-settled
``SPX`` (against the opening SET) alongside a PM-settled ``SPXW`` (against the
close). Measured on the live 2026-08-21 chain: AM alone maxes at 7650, PM alone
at 7545, and blending them gives 7630 — a number belonging to neither event, with
nothing about it to signal that it is meaningless. A date-keyed guard sees one
date and waves it through.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from strikemetrics.errors import InvalidInputError
from strikemetrics.types import ChainRow


@dataclass(frozen=True, slots=True)
class StrikePain:
    strike: float
    total_loss: float   # dollar loss to option buyers if expiry settles here
    call_oi: int
    put_oi: int


@dataclass(frozen=True, slots=True)
class MaxPainResult:
    max_pain_strike: float
    total_loss_at_max_pain: float
    per_strike: tuple[StrikePain, ...]   # ascending by strike


def compute_max_pain(rows: Iterable[ChainRow]) -> MaxPainResult | None:
    """Compute max pain from one settlement's rows.

    Rows with ``None`` or zero open interest carry no pain and are skipped.
    Returns ``None`` when nothing carries open interest, there is no pain
    surface to minimize.

    Raises ``InvalidInputError`` if the rows span more than one settlement — a
    different expiration date, or the same date with a different ``settlement``.
    Rows whose expiration is ``None`` are accepted; the field is optional on
    ``ChainRow`` and a caller that never sets it is not making the mistake this
    guards against.
    """
    rows = list(rows)
    events = {r.settlement_key for r in rows if r.settlement_key is not None}
    if len(events) > 1:
        raise InvalidInputError(
            f'max pain is defined for one settlement; got {len(events)} '
            f'({", ".join(sorted(events))}). Compute it per settlement — note '
            'that one expiration date can carry two, e.g. an AM-settled SPX and '
            'a PM-settled SPXW on the same monthly.'
        )
    call_oi: dict[float, int] = {}
    put_oi: dict[float, int] = {}
    call_exposure: dict[float, float] = {}
    put_exposure: dict[float, float] = {}

    for row in rows:
        if not row.open_interest:   # None or 0: no exposure at this contract
            continue
        oi = row.open_interest
        exposure = float(oi) * row.multiplier
        if row.is_call:
            call_oi[row.strike] = call_oi.get(row.strike, 0) + oi
            call_exposure[row.strike] = call_exposure.get(row.strike, 0.0) + exposure
        else:
            put_oi[row.strike] = put_oi.get(row.strike, 0) + oi
            put_exposure[row.strike] = put_exposure.get(row.strike, 0.0) + exposure

    all_strikes = sorted(set(call_oi) | set(put_oi))
    if not all_strikes:
        return None

    per_strike = []
    for s in all_strikes:
        call_loss = sum((s - k) * exp for k, exp in call_exposure.items() if k < s)
        put_loss = sum((k - s) * exp for k, exp in put_exposure.items() if k > s)
        per_strike.append(StrikePain(
            strike=s,
            total_loss=call_loss + put_loss,
            call_oi=call_oi.get(s, 0),
            put_oi=put_oi.get(s, 0),
        ))

    best = min(per_strike, key=lambda p: p.total_loss)
    return MaxPainResult(
        max_pain_strike=best.strike,
        total_loss_at_max_pain=best.total_loss,
        per_strike=tuple(per_strike),
    )
