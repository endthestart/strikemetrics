"""Strike walls: price levels where positioning concentrates support/resistance.

Scores every strike on four signals, each min-max normalized to [0, 1] across
the chain, then blended into a composite:

- OI concentration: total (call + put) open interest at the strike.
- GEX magnitude: |per-strike gamma exposure| from :func:`compute_gex`.
- directional PCR: put/call OI imbalance at the strike.
- max-pain proximity: inverse distance to the max-pain strike, in units of the
  chain's median strike spacing, ``1 / (1 + |strike - pain| / step)``.

Default weights (0.35 / 0.30 / 0.20 / 0.15) came from the source system's
calibration; pass a ``WallWeights`` to re-blend. A strike above spot is labelled
``resistance``, below ``support``, at spot ``pivot``.
"""

import itertools
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from strikemetrics.errors import InvalidInputError
from strikemetrics.gex import GEXProfile
from strikemetrics.types import ChainRow


@dataclass(frozen=True, slots=True)
class WallWeights:
    """Blend weights for the four wall signals (need not sum to 1, but the
    defaults do).

    ``gex`` is deliberately the smallest weight despite being the most
    sophisticated signal. Per-strike GEX is ``gamma x OI x multiplier x spot²``,
    and across a real chain OI spans orders of magnitude while gamma varies
    smoothly, so |GEX| is largely a restatement of open interest. Measured on XSP:
    ``r = +0.957`` and ``+0.988`` on two liquid expirations (the correlation falls
    on thin chains, where gamma has room to matter). Weighting the pair as two
    independent signals spends most of the blend ranking strikes by size twice.

    ``pcr`` and ``max_pain`` are the signals that carry information the others do
    not (|r| < 0.35 against everything), which is why they hold half the weight
    between them.

    These are a structural de-duplication, not a calibration. Nothing here has
    been fitted against whether a wall subsequently acted as support or
    resistance; that needs forward-return data. Treat them as a defensible
    starting point and pass your own once you can measure outcomes.
    """

    oi: float = 0.35
    gex: float = 0.15
    pcr: float = 0.30
    max_pain: float = 0.20


# Bound once at import: the defaults are a frozen value, so a shared instance is
# the same object every call and keeps it out of the signature's evaluation.
_DEFAULT_WEIGHTS = WallWeights()


@dataclass(frozen=True, slots=True)
class StrikeWall:
    strike: float
    composite_score: float
    oi_score: float
    gex_score: float
    pcr_score: float
    max_pain_score: float
    wall_type: str          # 'resistance' | 'support' | 'pivot'
    total_oi: int
    net_gex: float


@dataclass(frozen=True, slots=True)
class StrikeWallResult:
    walls: tuple[StrikeWall, ...]   # descending by composite score, top N
    strike_count: int


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. All-identical values normalize to zeros."""
    if not values:
        return []
    min_v, max_v = min(values), max(values)
    if max_v == min_v:
        return [0.0] * len(values)
    span = max_v - min_v
    return [(v - min_v) / span for v in values]


def _resolve_pure_put_strikes(pcr: list[float], positions: list[int]) -> None:
    """Give every call-less strike the largest finite ratio on the chain, in place.

    A strike with puts and no calls has an undefined ratio and is the most
    put-skewed strike present, so it belongs at the top of this signal. It must not
    carry its open-interest count: `pcr` is min-max normalized, and a count of
    30,000 among ratios of 2-5 maps every real reading to ~0.0001.

    If no strike has a finite ratio, they all tie and normalize to zero.
    """
    if not positions:
        return
    finite = [v for i, v in enumerate(pcr) if i not in set(positions)]
    ceiling = max(finite, default=0.0)
    for i in positions:
        pcr[i] = ceiling


def _max_pain_proximity(strike: float, max_pain_strike: float, strike_step: float) -> float:
    """Inverse distance to max pain, bounded to (0, 1]; 1.0 at max pain."""
    if strike_step <= 0:
        return 1.0 if strike == max_pain_strike else 0.0
    return 1.0 / (1.0 + abs(strike - max_pain_strike) / strike_step)


def _classify_wall_type(strike: float, spot: float) -> str:
    if strike > spot:
        return 'resistance'
    if strike < spot:
        return 'support'
    return 'pivot'


def compute_strike_walls(
    rows: Iterable[ChainRow],
    gex_profile: GEXProfile | None,
    max_pain_strike: float | None,
    spot: float,
    *,
    top_n: int = 5,
    weights: WallWeights = _DEFAULT_WEIGHTS,
) -> StrikeWallResult:
    """Score and rank strikes by positioning signals; return the top ``top_n``.

    ``gex_profile`` (from :func:`strikemetrics.compute_gex`) and
    ``max_pain_strike`` (from :func:`strikemetrics.compute_max_pain`) are
    optional. A missing signal contributes zero rather than failing, since each is
    legitimately absent on thin chains.
    """
    spot = float(spot)
    if spot <= 0:
        raise InvalidInputError(f'spot must be positive, got {spot}')
    if top_n <= 0:
        raise InvalidInputError(f'top_n must be positive, got {top_n}')

    call_oi: dict[float, int] = {}
    put_oi: dict[float, int] = {}
    for row in rows:
        if row.open_interest is None:
            continue
        side = call_oi if row.is_call else put_oi
        side[row.strike] = side.get(row.strike, 0) + row.open_interest

    all_strikes = sorted(set(call_oi) | set(put_oi))
    if not all_strikes:
        return StrikeWallResult(walls=(), strike_count=0)

    # Median gap between consecutive strikes = the chain's natural step size.
    gaps = [b - a for a, b in itertools.pairwise(all_strikes)]
    strike_step = statistics.median(gaps) if gaps else 1.0

    gex_by_strike: dict[float, float] = {}
    if gex_profile is not None:
        gex_by_strike = {entry.strike: entry.gex for entry in gex_profile.per_strike}

    oi_signals: list[float] = []
    gex_signals: list[float] = []
    pcr_signals: list[float] = []
    max_pain_signals: list[float] = []
    raw_total_oi: list[int] = []
    raw_net_gex: list[float] = []

    pure_put_strikes: list[int] = []     # positions to fill in once the max is known

    for i, s in enumerate(all_strikes):
        c = call_oi.get(s, 0)
        p = put_oi.get(s, 0)
        raw_total_oi.append(c + p)

        gex_val = gex_by_strike.get(s, 0.0)
        raw_net_gex.append(gex_val)

        if c > 0:
            pcr = p / c
        elif p > 0:
            # Undefined ratio; resolved against the chain's maximum once every
            # strike has been read. See _resolve_pure_put_strikes.
            pcr = 0.0
            pure_put_strikes.append(i)
        else:
            pcr = 0.0

        mp_prox = (_max_pain_proximity(s, max_pain_strike, strike_step)
                   if max_pain_strike is not None else 0.0)

        oi_signals.append(float(c + p))
        gex_signals.append(abs(gex_val))
        pcr_signals.append(pcr)
        max_pain_signals.append(mp_prox)

    _resolve_pure_put_strikes(pcr_signals, pure_put_strikes)

    oi_norm = _normalize(oi_signals)
    gex_norm = _normalize(gex_signals)
    pcr_norm = _normalize(pcr_signals)
    mp_norm = _normalize(max_pain_signals)

    walls = [
        StrikeWall(
            strike=s,
            composite_score=(weights.oi * oi_norm[i] + weights.gex * gex_norm[i]
                             + weights.pcr * pcr_norm[i] + weights.max_pain * mp_norm[i]),
            oi_score=oi_norm[i],
            gex_score=gex_norm[i],
            pcr_score=pcr_norm[i],
            max_pain_score=mp_norm[i],
            wall_type=_classify_wall_type(s, spot),
            total_oi=raw_total_oi[i],
            net_gex=raw_net_gex[i],
        )
        for i, s in enumerate(all_strikes)
    ]
    walls.sort(key=lambda w: w.composite_score, reverse=True)
    return StrikeWallResult(walls=tuple(walls[:top_n]), strike_count=len(all_strikes))
