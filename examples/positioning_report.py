"""Example: a full positioning report from a synthetic chain, no data source.

Builds a plausible one-expiration SPX-style chain (puts stacked below spot,
calls above), then runs every strikemetrics analytic and prints a small report.
A real caller would build the same ``ChainRow``/``Trade`` records from its
broker SDK or vendor API; nothing else changes.

Run: ``python positioning_report.py``
"""

from strikemetrics import (
    ChainRow,
    Trade,
    aggregate_delta_oi,
    compute_delta_oi,
    compute_gex,
    compute_max_pain,
    compute_oi_pcr,
    compute_strike_walls,
    compute_volume_pcr,
)

SPOT = 6050.0
EXPIRATION = '2026-08-21'

# One expiration, both sides listed at every strike (as real chains are):
# (strike, type, gamma, open_interest, volume). OI concentrates where large
# players positioned: puts at 5900/6000, calls at 6200.
CHAIN = [
    (5800, 'put',  0.0004, 31_000, 4_200), (5800, 'call', 0.0004, 1_800, 150),
    (5850, 'put',  0.0005, 12_000, 1_100), (5850, 'call', 0.0005, 2_300, 180),
    (5900, 'put',  0.0007, 45_000, 9_800), (5900, 'call', 0.0007, 4_200, 300),
    (5950, 'put',  0.0009, 16_000, 2_400), (5950, 'call', 0.0009, 6_200, 500),
    (6000, 'put',  0.0011, 52_000, 12_500), (6000, 'call', 0.0011, 14_300, 1_900),
    (6050, 'put',  0.0013, 14_000, 3_900), (6050, 'call', 0.0013, 16_500, 3_100),
    (6100, 'put',  0.0012, 6_200, 900),    (6100, 'call', 0.0012, 57_000, 8_700),
    (6150, 'put',  0.0009, 2_900, 400),    (6150, 'call', 0.0009, 22_500, 2_200),
    (6200, 'put',  0.0007, 1_800, 200),    (6200, 'call', 0.0007, 91_500, 14_300),
    (6250, 'put',  0.0005, 900, 100),      (6250, 'call', 0.0005, 19_500, 1_600),
    (6300, 'put',  0.0004, 600, 80),       (6300, 'call', 0.0004, 40_500, 3_800),
]


def rows_today() -> list[ChainRow]:
    return [
        ChainRow(strike=s, option_type=t, gamma=g, open_interest=oi,
                 volume=vol, expiration=EXPIRATION)
        for s, t, g, oi, vol in CHAIN
    ]


def rows_yesterday() -> list[ChainRow]:
    """Same chain a day earlier: puts were lighter (positions built overnight)."""
    return [
        ChainRow(strike=s, option_type=t, gamma=g,
                 open_interest=oi - (2_000 if t == 'put' else 500),
                 volume=vol, expiration=EXPIRATION)
        for s, t, g, oi, vol in CHAIN
    ]


if __name__ == '__main__':
    rows = rows_today()

    print(f'Positioning report, spot {SPOT:,.0f}, expiration {EXPIRATION}\n')

    gex = compute_gex(rows, SPOT)
    print(f'Net GEX        {gex.net_gex:+,.0f}  '
          f'({"dealers dampen moves" if gex.net_gex > 0 else "dealers amplify moves"})')
    print(f'Gamma flip     {gex.gamma_flip}')
    print(f'Call wall      {gex.call_wall:,.0f}')
    print(f'Put wall       {gex.put_wall:,.0f}')

    pain = compute_max_pain(rows)
    print(f'Max pain       {pain.max_pain_strike:,.0f}  '
          f'(buyers lose ${pain.total_loss_at_max_pain:,.0f} if it settles there)')

    oi_pcr = compute_oi_pcr(rows)
    print(f'OI PCR         {oi_pcr.ratio:.2f}  '
          f'({oi_pcr.put_oi:,} puts / {oi_pcr.call_oi:,} calls)')

    tape = [Trade('put', 9_000), Trade('put', 6_500), Trade('call', 11_000)]
    vol_pcr = compute_volume_pcr(tape)
    print(f'Volume PCR     {vol_pcr.ratio:.2f}  '
          f'({vol_pcr.put_volume:,} puts / {vol_pcr.call_volume:,} calls)')

    print('\nTop strike walls (OI + GEX + PCR + max-pain blend):')
    walls = compute_strike_walls(rows, gex, pain.max_pain_strike, SPOT)
    for w in walls.walls:
        print(f'  {w.strike:>7,.0f}  score {w.composite_score:.2f}  '
              f'{w.wall_type:<10}  OI {w.total_oi:>7,}  GEX {w.net_gex:+,.0f}')

    print('\nDay-over-day open-interest change:')
    delta = aggregate_delta_oi(compute_delta_oi(rows, rows_yesterday()))
    s = delta.underlying_summary
    print(f'  calls {s.net_call_delta_oi:+,}   puts {s.net_put_delta_oi:+,}   '
          f'net {s.net_total_delta_oi:+,}  '
          f'({s.contract_count} contracts, quality: {s.data_quality})')
