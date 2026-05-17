"""Regression test: currency-prefix tolerance in score_case.

Caught from user audit — GPT-4o output '780,803.18' for expected
'$780,803.18' was previously marked incorrect. With the
_strip_currency fallback in _contains_loose, both the prefixed and
unprefixed forms now match (in either direction).
"""
from pdfhell.case import HellCase
from pdfhell.scorer import score_case


def _case(expected: str, forbidden=()) -> HellCase:
    return HellCase(
        id="t",
        trap_family="hidden_ocr_mismatch",
        seed=1,
        question="q?",
        expected_answer=expected,
        forbidden_answers=list(forbidden),
    )


class TestCurrencyTolerance:
    def test_unprefixed_output_matches_dollar_expected(self):
        s = score_case(_case("$780,803.18"), "The total is 780,803.18.")
        assert s.correct
        assert s.matched_expected

    def test_dollar_output_matches_dollar_expected(self):
        s = score_case(_case("$780,803.18"), "Total: $780,803.18")
        assert s.correct

    def test_unprefixed_expected_matches_dollar_output(self):
        s = score_case(_case("780,803.18"), "The amount is $780,803.18.")
        assert s.correct

    def test_euro_prefix_tolerated(self):
        s = score_case(_case("€1,234.56"), "Refund: 1,234.56")
        assert s.correct

    def test_does_not_match_wrong_number(self):
        s = score_case(_case("$780,803.18"), "Total: $780,000.")
        assert not s.correct
