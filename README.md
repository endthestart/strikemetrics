# strikemetrics

Dependency-free option-chain positioning analytics in pure Python. Feed it plain
records from any data source (broker SDK, vendor API, database) and ask for the
chain's positioning picture: gamma exposure (GEX), max pain, strike walls,
put/call ratios, and day-over-day open-interest deltas.

- No dependencies. Stdlib only. No pandas, no numpy, no Django, no broker SDK,
  no network or disk I/O. The package never fetches data; you hand it rows and it
  hands back typed results.
- Unknown is never zero. A missing greek or open-interest value is `None` and
  stays that way: rows are skipped or flagged (`data_quality='partial'`,
  `unknown_contract_count`) rather than zero-filled into a biased total.
  Undefined ratios (zero call side) are `None`, with the raw side totals still
  reported.
- Floats by design. These are positioning analytics, not accounting. Anything
  that settles to cash belongs in an exact-`Decimal` domain; see the sibling
  package [`optionstruct`](https://github.com/endthestart/optionstruct), which
  models a position's legs, payoff and risk exactly. strikemetrics models the
  whole chain. One exception: `oi_pcr_decimal` returns an exact `Decimal` for
  callers persisting the figure.

```python
from strikemetrics import ChainRow, compute_gex, compute_max_pain, compute_strike_walls

rows = [
    ChainRow(strike=5900, option_type='put',  gamma=0.0007, open_interest=18_000),
    ChainRow(strike=6000, option_type='put',  gamma=0.0011, open_interest=25_000),
    ChainRow(strike=6100, option_type='call', gamma=0.0013, open_interest=22_000),
    ChainRow(strike=6200, option_type='call', gamma=0.0008, open_interest=30_000),
]
spot = 6050.0

gex = compute_gex(rows, spot)
gex.net_gex       # dollars to hedge per 1% move; positive → dealers dampen moves
gex.zero_cross_strike  # strike where cumulative GEX changes sign. NOT the
                       # vendor "zero gamma level", which solves for a spot
gex.call_wall     # largest positive-GEX strike (pin/resistance)
gex.put_wall      # most negative-GEX strike (magnet/support)

pain = compute_max_pain(rows)             # one expiration's rows
pain.max_pain_strike                      # buyers' worst-case settlement price

walls = compute_strike_walls(rows, gex, pain.max_pain_strike, spot)
walls.walls[0]    # top strike by blended OI/GEX/PCR/max-pain score
```

## Model

| Piece | What it is |
|---|---|
| `ChainRow` | one contract's chain slice: strike, type, gamma, OI, volume, expiration, multiplier (default 100) |
| `Trade` | one trade-tape record (type + size), for volume PCR |
| `compute_gex` → `GEXProfile` | net GEX, gamma flip, call/put walls, per-strike profile |
| `compute_max_pain` → `MaxPainResult` | max-pain strike + full per-strike loss surface |
| `compute_strike_walls` → `StrikeWallResult` | strikes ranked by blended positioning score (`WallWeights` to re-blend, `top_n` to widen) |
| `compute_volume_pcr` / `compute_oi_pcr` | put/call ratios with raw side totals |
| `compute_delta_oi` + `aggregate_delta_oi` | day-over-day ΔOI per contract → per expiration → per underlying, with explicit unknown-tracking |

Inputs accept friendly types (`Decimal`/`str` strikes, `'call'`/`'PUT'` type
strings) and normalize on construction. Results are frozen dataclasses.

## Conventions

- GEX uses the standard dealer-positioning convention: calls contribute
  positive gamma exposure, puts negative, each
  `gamma x OI x multiplier x spot² x 0.01`. The trailing `0.01` is a unit
  conversion. It gives the figure as GEX is normally quoted: dollars of dealer
  delta to hedge per 1% move in the underlying. Without it the numbers read 100x
  larger than published GEX. The gamma flip is the first strike (ascending) where
  cumulative GEX changes sign.
- Max pain is computed over a single expiration's rows. Pass one
  expiration at a time (mixing expirations blends the surface meaninglessly).
- Strike-wall weights default to OI 0.35 / GEX 0.15 / PCR 0.30 / max-pain 0.20;
  pass `WallWeights` to re-blend. GEX carries the smallest weight on purpose:
  per-strike GEX is `gamma x OI x …`, so on a liquid chain it largely restates
  open interest (measured r = +0.96 to +0.99 on XSP). These weights de-duplicate
  that overlap; they are not fitted against whether a wall held.
- ΔOI compares two morning snapshots (OI prints once daily). The tape shows
  volume; ΔOI shows commitment, meaning where positions actually opened or
  closed.

## Scope

Positioning metrics only. No IV surface, no greeks computation (bring your own
gamma; every feed supplies it, and `optionstruct.pricing` has Black-Scholes for
offline values), no data fetching, no charting. Bad parameters raise
(`InvalidInputError`); absent data never does, since no data is a market
condition rather than a bug.

`examples/positioning_report.py` builds a synthetic chain and prints every
metric, so you can see the full API without any data source.

## Provenance

Extracted from a production options-flow system. The computational cores and
their test suites, including hand-calculated expectations, came over intact.

## License

MIT.
