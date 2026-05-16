"""Render a :class:`SuiteReport` as JUnit XML for CI consumption.

GitHub Actions, GitLab CI, Jenkins, CircleCI, and most other CI runners
display JUnit XML natively in their PR / merge-request panel. Failures
show up as red rows on the PR with the model output and expected
answer in the failure message.

The rendered XML follows the de-facto JUnit dialect (Ant/Maven-style)
that everyone parses. We classify outcomes as:

- ``correct=True``    → passing testcase, no children
- ``fell_for_trap``   → ``<failure>`` (this is the diagnostic signal)
- ``refused``         → ``<skipped>`` (model wouldn't answer — not a quality fail)
- everything else     → ``<failure>``

We deliberately don't emit ``<error>`` — pdfhell's upstream errors
(provider down, SDK missing) get caught in the runner and recorded as
the model's text output starting with ``[error]``. Surfacing them as
``<error>`` would noise the dashboard for transient infra issues.
"""
from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET

from .scorer import SuiteReport


def _suite_name(report: SuiteReport) -> str:
    """Slug-ish name for the JUnit suite — 'pdfhell.<suite>.<model>'."""
    safe_model = report.model.replace("/", ".").replace(":", ".")
    return f"pdfhell.{report.suite}.{safe_model}"


def report_to_junit(report: SuiteReport) -> str:
    """Return a JUnit XML string for ``report``.

    The XML is human-readable and round-trips through every CI parser
    we've tested. Failure messages include the expected and observed
    answers so on-call doesn't have to dig through the runs JSON.
    """
    failures = sum(1 for c in report.cases if not c.correct and not c.refused)
    skipped = sum(1 for c in report.cases if c.refused)
    testsuite = ET.Element(
        "testsuite",
        {
            "name": _suite_name(report),
            "tests": str(report.n),
            "failures": str(failures),
            "errors": "0",
            "skipped": str(skipped),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )
    for c in report.cases:
        case_el = ET.SubElement(
            testsuite,
            "testcase",
            {
                "name": c.case_id,
                "classname": c.trap_family,
            },
        )
        if c.refused:
            skipped_el = ET.SubElement(case_el, "skipped", {"message": "model refused"})
            skipped_el.text = c.model_output[:200]
        elif not c.correct:
            kind = "fell_for_trap" if c.fell_for_trap else "hallucination"
            failure_el = ET.SubElement(
                case_el,
                "failure",
                {
                    "type": kind,
                    "message": (
                        f"expected={c.expected!r}; got={c.model_output[:80]!r}"
                    ),
                },
            )
            details = [
                f"expected_answer: {c.expected}",
                f"model_output:    {c.model_output}",
            ]
            if c.matched_forbidden:
                details.append(f"matched_forbidden: {c.matched_forbidden}")
            if c.failure_mode:
                details.append(f"failure_mode: {c.failure_mode}")
            failure_el.text = "\n".join(details)
    testsuites = ET.Element("testsuites")
    testsuites.append(testsuite)
    # ET in 3.10+ supports short_empty_elements but xml_declaration is what CIs expect.
    return ET.tostring(testsuites, encoding="unicode", xml_declaration=True)


__all__ = ["report_to_junit"]
