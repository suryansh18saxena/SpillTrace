"""Deterministic synthetic data for development and demonstration (FR-020, CON-009).

Two things this module is careful about:

1. **It only synthesises observations** — a satellite scene, a slick polygon, wind and
   current fields, and raw AIS messages.  Everything downstream (look-alike
   verification, reverse drift, AIS cleaning, trajectory building, correlation, scoring,
   reporting) runs the *real* algorithm on that synthetic input.  A demo that faked the
   conclusions would prove nothing.
2. **Everything it produces is labelled.**  `data_provenance = SYNTHETIC`, vessel names
   carry a `(SYNTHETIC)` suffix, and the API attaches a notice.  Synthetic data must
   never be mistakable for a real observation.

Given the same scenario and seed, the output is byte-for-byte identical.
"""

from spilltrace.demo.scenarios import SCENARIOS, Scenario, get_scenario

__all__ = ["SCENARIOS", "Scenario", "get_scenario"]
