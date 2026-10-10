import sys
import unittest

from dashboard.seed_validation import (
    MAX_WEB_SEED_DIGITS, effective_seed_digit_limit, parse_seed_text, validate_web_seed,
)


class SeedValidationTests(unittest.TestCase):
    def test_accepts_positive_negative_null_and_normalizes_negative_zero(self):
        self.assertEqual(parse_seed_text("123"), 123)
        self.assertEqual(parse_seed_text("-123"), -123)
        self.assertEqual(parse_seed_text("-0"), 0)
        self.assertIsNone(validate_web_seed(None))

    def test_rejects_noncanonical_text_and_boolean_values(self):
        for value in ("+1", " 1", "01", "-01", "1.0", "1e2", "", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_seed_text(value)
        with self.assertRaisesRegex(ValueError, "整数或null"):
            validate_web_seed(True)

    def test_uses_project_limit_when_python_limit_is_disabled(self):
        old_limit = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(0)
            self.assertEqual(effective_seed_digit_limit(), MAX_WEB_SEED_DIGITS)
            self.assertEqual(len(str(parse_seed_text("9" * MAX_WEB_SEED_DIGITS))),
                             MAX_WEB_SEED_DIGITS)
            self.assertEqual(parse_seed_text("-" + "9" * MAX_WEB_SEED_DIGITS),
                             -int("9" * MAX_WEB_SEED_DIGITS))
            with self.assertRaisesRegex(ValueError, "最多允许4300位"):
                parse_seed_text("9" * (MAX_WEB_SEED_DIGITS + 1))
        finally:
            sys.set_int_max_str_digits(old_limit)

    def test_respects_a_lower_python_limit_and_checks_integer_without_stringifying(self):
        old_limit = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(640)
            self.assertEqual(effective_seed_digit_limit(), 640)
            self.assertEqual(parse_seed_text("9" * 640), int("9" * 640))
            with self.assertRaisesRegex(ValueError, "最多允许640位"):
                parse_seed_text("9" * 641)
            with self.assertRaisesRegex(ValueError, "最多允许640位"):
                validate_web_seed(10 ** 640)
        finally:
            sys.set_int_max_str_digits(old_limit)


if __name__ == "__main__":
    unittest.main()
