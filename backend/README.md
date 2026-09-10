# spilltrace (backend)

Single Python package serving three runtime roles:

* `python -m spilltrace.api` — FastAPI application
* `python -m spilltrace.worker` — job worker pool
* `python -m spilltrace.worker.ais_ingestor` — long-lived AIS stream consumer

Layering rule (enforced by `tests/unit/test_import_layering.py`):
`core` imports nothing from `adapters`, `db`, `api` or `worker`.
