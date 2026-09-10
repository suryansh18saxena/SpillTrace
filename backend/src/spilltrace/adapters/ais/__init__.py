"""AIS providers.

``synthetic`` generates deterministic traffic for any bounding box and time window and
is always available.  ``aisstream`` is the prototype live source described in the PRD;
it is a *stream*, so it can answer "what is happening now" but not "what happened last
Tuesday" — see :meth:`AISProvider.historical`.
"""

from __future__ import annotations

from spilltrace.config import Settings, get_settings
from spilltrace.core.ports import AISProvider
from spilltrace.logging import get_logger

log = get_logger(__name__)


def build_ais_provider(settings: Settings | None = None) -> AISProvider:
    settings = settings or get_settings()
    if settings.ais_provider == "aisstream":
        if not settings.aisstream_api_key:
            # Degrade loudly rather than connecting with no key and stalling silently:
            # an AISStream subscription with a bad key produces no error, just silence.
            log.warning(
                "aisstream_selected_without_key_using_synthetic",
                remedy="set AISSTREAM_API_KEY",
            )
        else:
            try:
                from spilltrace.adapters.ais.aisstream import AISStreamProvider

                return AISStreamProvider(settings)
            except ImportError as exc:
                log.warning("aisstream_unavailable_using_synthetic", error=str(exc))
    from spilltrace.adapters.ais.synthetic import SyntheticAISProvider

    return SyntheticAISProvider()


__all__ = ["build_ais_provider"]
