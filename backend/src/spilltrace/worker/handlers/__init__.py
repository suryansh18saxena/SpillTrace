"""Job handlers.

Importing this package registers every handler with the worker registry.
"""

from spilltrace.worker.handlers import (
    ais,
    attribution,
    demo,
    drift,
    report,
    sar,
    satellite,
    verify,
)

__all__ = ["ais", "attribution", "demo", "drift", "report", "sar", "satellite", "verify"]
