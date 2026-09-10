"""Evidence report generation (FR-018, AC-12, AC-13).

The report is the artifact an investigator actually works from, so it is built to be
*checkable*: every number is accompanied by where it came from, which software version
produced it, and what its limitations are.  A report that only stated conclusions would
be worse than useless in this domain.
"""

from spilltrace.core.report.assemble import ReportData, assemble_report
from spilltrace.core.report.html import render_html

__all__ = ["ReportData", "assemble_report", "render_html"]
