"""strikemetrics, dependency-free option-chain positioning analytics.

Pure Python, stdlib only. No pandas, no Django, no broker SDK, no I/O. Feed it
plain :class:`ChainRow` records from any data source and ask for the chain's
positioning picture: gamma exposure (GEX), max pain, strike walls, put/call
ratios, and day-over-day open-interest deltas.

    from strikemetrics import ChainRow, compute_gex, compute_max_pain

    rows = [
        ChainRow(strike=100, option_type='call', gamma=0.04, open_interest=500),
        ChainRow(strike=105, option_type='put', gamma=0.05, open_interest=400),
    ]
    gex = compute_gex(rows, spot=105.0)
    gex.net_gex      # signed dollar-gamma; positive = dealers dampen moves
    gex.call_wall    # 100.0
    pain = compute_max_pain(rows)   # needs open interest only

Sibling package: ``optionstruct`` models a *position* (legs, payoff, exact
risk, Decimal); strikemetrics models the *whole chain's* positioning (floats , 
analytics, not accounting).
"""

from strikemetrics.delta_oi import (
    ContractDeltaOI,
    DeltaOIResult,
    ExpirationDeltaOI,
    UnderlyingDeltaOI,
    aggregate_delta_oi,
    compute_delta_oi,
)
from strikemetrics.errors import InvalidInputError, StrikeMetricsError
from strikemetrics.gex import GEXProfile, StrikeGEX, compute_gex
from strikemetrics.max_pain import MaxPainResult, StrikePain, compute_max_pain
from strikemetrics.pcr import (
    OIPCR,
    VolumePCR,
    compute_oi_pcr,
    compute_volume_pcr,
    oi_pcr_decimal,
)
from strikemetrics.types import DEFAULT_MULTIPLIER, ChainRow, OptionType, Trade
from strikemetrics.walls import (
    StrikeWall,
    StrikeWallResult,
    WallWeights,
    compute_strike_walls,
)

__version__ = '0.0.4'

__all__ = [
    'DEFAULT_MULTIPLIER',
    'OIPCR',
    # inputs
    'ChainRow',
    'ContractDeltaOI',
    'DeltaOIResult',
    'ExpirationDeltaOI',
    'GEXProfile',
    # errors
    'InvalidInputError',
    'MaxPainResult',
    'OptionType',
    'StrikeGEX',
    'StrikeMetricsError',
    'StrikePain',
    'StrikeWall',
    'StrikeWallResult',
    'Trade',
    'UnderlyingDeltaOI',
    'VolumePCR',
    'WallWeights',
    '__version__',
    'aggregate_delta_oi',
    # open-interest deltas
    'compute_delta_oi',
    # gamma exposure
    'compute_gex',
    # max pain
    'compute_max_pain',
    'compute_oi_pcr',
    # strike walls
    'compute_strike_walls',
    # put/call ratios
    'compute_volume_pcr',
    'oi_pcr_decimal',
]
