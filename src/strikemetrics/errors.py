"""Exception hierarchy for strikemetrics.

One deliberate distinction:

- Bad inputs raise. A nonsensical parameter (non-positive spot, negative
  size, a row without the expiration an analytic needs) is a caller bug , 
  ``InvalidInputError``, loudly.
- Absent data does not raise. A chain with no open interest, or a metric
  whose denominator is legitimately zero, is a real market condition, those
  return ``None`` / flagged results (``data_quality``), never a fabricated
  number and never an exception.
"""


class StrikeMetricsError(Exception):
    """Base class for every error raised by strikemetrics."""


class InvalidInputError(StrikeMetricsError, ValueError):
    """A parameter is outside its valid domain (e.g. spot <= 0)."""
