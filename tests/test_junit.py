"""Tests for the JUnit XML reporter.

Verify the XML round-trips through a parser so it'll actually render in
GitHub Actions / GitLab CI. The renderer must:

- emit a single ``<testsuites>`` root with one ``<testsuite>``
- count tests, failures, skipped correctly
- mark refused cases as ``<skipped>``, wrong answers as ``<failure>``
- distinguish fell_for_trap from hallucination via the failure ``type``
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from pdfhell.case import HellCase
from pdfhell.junit import report_to_junit
from pdfhell.scorer import score_case, summarise


def _make_case(expected: str, forbidden: list[str] | None = None) -> HellCase:
    return HellCase(
        id="test-0001",
        trap_family="hidden_ocr_mismatch",
        seed=1,
        question="What is the total?",
        expected_answer=expected,
        forbidden_answers=forbidden or [],
        metadata={"expected_failure_mode": "Trusted hidden OCR."},
    )


def test_junit_xml_parses_and_counts():
    cases = [
        # Pass
        score_case(_make_case("$1.00"), "$1.00"),
        # Fail (trap)
        score_case(_make_case("$2.00", forbidden=["$3.00"]), "$3.00"),
        # Skip (refused)
        score_case(_make_case("$4.00"), "I cannot determine that."),
        # Fail (hallucination)
        score_case(_make_case("$5.00"), "$99.00"),
    ]
    report = summarise("anthropic:claude-haiku-4-5", "mini", cases)
    xml = report_to_junit(report)

    root = ET.fromstring(xml)
    assert root.tag == "testsuites"
    suite = root.find("testsuite")
    assert suite is not None
    assert suite.attrib["tests"] == "4"
    assert suite.attrib["failures"] == "2"  # trap + hallucination
    assert suite.attrib["skipped"] == "1"  # refusal
    assert suite.attrib["errors"] == "0"

    cases_el = suite.findall("testcase")
    assert len(cases_el) == 4

    # The trap-caught case has type="fell_for_trap".
    failure_types = [
        f.attrib.get("type")
        for tc in cases_el
        for f in tc.findall("failure")
    ]
    assert "fell_for_trap" in failure_types
    assert "hallucination" in failure_types

    # The refused case has a <skipped> child.
    skipped = [tc for tc in cases_el if tc.find("skipped") is not None]
    assert len(skipped) == 1


def test_junit_xml_handles_empty_report():
    report = summarise("anthropic:claude-haiku-4-5", "mini", [])
    xml = report_to_junit(report)
    root = ET.fromstring(xml)
    suite = root.find("testsuite")
    assert suite is not None
    assert suite.attrib["tests"] == "0"
    assert suite.findall("testcase") == []
