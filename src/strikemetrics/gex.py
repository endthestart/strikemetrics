"""Gamma exposure (GEX): net dealer gamma per strike, flip point, walls.

Per-contract GEX = ``sign x gamma x OI x multiplier x spot² x 0.01``, with the
conventional dealer-positioning signs: **calls +1, puts -1**.

Those signs encode an assumption about who holds what, and it is worth stating
correctly because the arithmetic is unforgiving: a *long* option position has
positive gamma and a *short* one has negative gamma, whichever right it is. So
``+1`` on calls means dealers are assumed **long** calls, and ``-1`` on puts
means dealers are assumed **short** puts.

That is the SqueezeMetrics convention, from the paper that introduced the measure
(*Gamma Exposure*, SqueezeMetrics, December 2017,
https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf), assumptions 2
and 3 verbatim:

    2. Call options are sold by investors; bought by market-makers. ... the
       practice of call overwriting (and stock collaring) drives the market for
       calls.
    3. Put options are bought by investors; sold by market-makers. ... The
       "protective put" commands a premium

and its formulas: ``GEX = Γ · OI · 100`` for calls, ``Γ · OI · (-100)`` for puts.

**It is an assumption, never a measurement.** Public open interest does not
identify the holder, so no published GEX figure — ours or a vendor's — observes
dealer inventory. It is a plausible story about broad-index customer flow
(portfolio hedgers buy puts, overwriters sell calls), and it degrades where that
story does not hold, most notably at very short DTE where premium selling runs
the other way.

The trailing 0.01 is a unit conversion. ``gamma`` is per $1 of underlying, so
``gamma x spot²`` is dollars of delta per 100% move. Scaling by 0.01 gives the
figure as it is normally quoted: dollars of dealer delta to hedge per 1% move.
Without it the numbers read 100x larger than published GEX.

Everything derived from GEX is a comparison (the sign of the net, which strike
carries the most, where the cumulative crosses zero), so the scaling changes no
ranking, flip point, or wall.

Aggregated per strike:

- net GEX: sum across the chain. Positive = dealers dampen moves (buy dips /
  sell rips), negative = dealers amplify them.
- zero-cross strike: the first strike (ascending) at which cumulative GEX changes
  sign. **This is not the "zero gamma level"** published by vendors, which solves
  for the *spot* at which total GEX would be zero, re-evaluating every option's
  gamma at each candidate spot. This one accumulates gamma measured at *today's*
  spot, so its answer depends on which strike the accumulation starts from — widen
  or narrow the strike window and the number moves. It is reported as a coarse
  read on where the per-strike sign flips, and computing the real thing needs a
  pricing model, which this package deliberately does not carry.
- call wall: strike with the largest positive GEX (upside pin/resistance).
- put wall: strike with the most negative GEX (downside magnet/support).

Rows missing gamma or open interest are skipped. Unknown stays unknown; it is
never treated as zero exposure.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from strikemetrics.errors import InvalidInputError
from strikemetrics.types import ChainRow

# Converts dollar-gamma-per-100%-move into the conventional per-1%-move figure.
# See the module docstring: this is a unit, not a tuning knob.
PERCENT_MOVE = 0.01


@dataclass(frozen=True, slots=True)
class StrikeGEX:
    strike: float
    gex: float          # dollars of dealer delta per 1% move in the underlying


@dataclass(frozen=True, slots=True)
class GEXProfile:
    net_gex: float
    # Renamed from `gamma_flip` in v0.0.3: it was never the gamma flip level. See
    # the module docstring — this is window-dependent and the real one is not.
    zero_cross_strike: float | None
    call_wall: float | None
    put_wall: float | None
    per_strike: tuple[StrikeGEX, ...]   # ascending by strike


def compute_gex(rows: Iterable[ChainRow], spot: float) -> GEXProfile:
    """Compute the chain's gamma-exposure profile at the given spot.

    Rows without both ``gamma`` and ``open_interest`` are skipped. An empty or
    fully-skipped chain yields a zero profile (no walls, no flip) rather than an
    error, no data is a market condition, not a caller bug.
    """
    spot = float(spot)
    if spot <= 0:
        raise InvalidInputError(f'spot must be positive, got {spot}')

    strike_gex: dict[float, float] = {}
    for row in rows:
        if row.gamma is None or row.open_interest is None:
            continue
        sign = 1 if row.is_call else -1
        gex = (sign * row.gamma * row.open_interest * row.multiplier
               * (spot ** 2) * PERCENT_MOVE)
        strike_gex[row.strike] = strike_gex.get(row.strike, 0.0) + gex

    if not strike_gex:
        return GEXProfile(net_gex=0.0, zero_cross_strike=None, call_wall=None,
                          put_wall=None, per_strike=())

    sorted_strikes = sorted(strike_gex)

    # Gamma flip: first strike where cumulative GEX (ascending) changes sign.
    cumulative = 0.0
    zero_cross: float | None = None
    prev_sign: int | None = None
    for s in sorted_strikes:
        cumulative += strike_gex[s]
        current_sign = 1 if cumulative >= 0 else -1
        if prev_sign is not None and current_sign != prev_sign:
            zero_cross = s
            break
        prev_sign = current_sign

    positive = {s: g for s, g in strike_gex.items() if g > 0}
    call_wall = max(positive, key=lambda s: positive[s]) if positive else None
    negative = {s: g for s, g in strike_gex.items() if g < 0}
    put_wall = min(negative, key=lambda s: negative[s]) if negative else None

    return GEXProfile(
        net_gex=sum(strike_gex.values()),
        zero_cross_strike=zero_cross,
        call_wall=call_wall,
        put_wall=put_wall,
        per_strike=tuple(StrikeGEX(s, strike_gex[s]) for s in sorted_strikes),
    )
