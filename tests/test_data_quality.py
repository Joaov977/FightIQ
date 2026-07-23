"""
tests/test_data_quality.py
---------------------------
Testes do módulo data_quality.py: validação de sanidade e normalização
de categoria de peso. Rode com:

    python -m unittest tests.test_data_quality -v
"""

import unittest
from datetime import date, timedelta

from data_quality import (
    normalize_weight_class,
    sanitize_age_reported,
    sanitize_birth_date,
    sanitize_fighter_dict,
    sanitize_percentage,
    sanitize_range,
    describe_sanitization,
)


class TestNormalizeWeightClass(unittest.TestCase):
    def test_case_variants_normalize_to_same_value(self):
        self.assertEqual(normalize_weight_class("MIDDLEWEIGHT"), "Middleweight")
        self.assertEqual(normalize_weight_class("middleweight"), "Middleweight")
        self.assertEqual(normalize_weight_class("Middleweight"), "Middleweight")

    def test_unrecognized_value_is_returned_cleaned_not_discarded(self):
        self.assertEqual(normalize_weight_class("  Catchweight  "), "Catchweight")

    def test_none_and_empty(self):
        self.assertIsNone(normalize_weight_class(None))
        self.assertIsNone(normalize_weight_class(""))


class TestSanitizeBirthDate(unittest.TestCase):
    def test_future_date_is_rejected(self):
        """Reprodução direta do bug original da idade '-1'."""
        future = (date.today() + timedelta(days=60)).isoformat()
        self.assertIsNone(sanitize_birth_date(future))

    def test_plausible_birth_date_is_kept(self):
        self.assertEqual(sanitize_birth_date("1990-05-10"), "1990-05-10")

    def test_implausibly_old_is_rejected(self):
        self.assertIsNone(sanitize_birth_date("1900-01-01"))

    def test_malformed_string_is_rejected(self):
        self.assertIsNone(sanitize_birth_date("not-a-date"))

    def test_none_and_empty(self):
        self.assertIsNone(sanitize_birth_date(None))
        self.assertIsNone(sanitize_birth_date(""))


class TestSanitizeAgeReported(unittest.TestCase):
    def test_plausible_age_is_kept(self):
        self.assertEqual(sanitize_age_reported("39"), 39)
        self.assertEqual(sanitize_age_reported(39), 39)

    def test_implausible_age_is_rejected(self):
        self.assertIsNone(sanitize_age_reported("-1"))
        self.assertIsNone(sanitize_age_reported("150"))
        self.assertIsNone(sanitize_age_reported("5"))

    def test_none_and_garbage(self):
        self.assertIsNone(sanitize_age_reported(None))
        self.assertIsNone(sanitize_age_reported("abc"))


class TestSanitizeRangeAndPercentage(unittest.TestCase):
    def test_height_out_of_human_range_rejected(self):
        self.assertIsNone(sanitize_range("30", 145.0, 215.0))
        self.assertEqual(sanitize_range("180", 145.0, 215.0), 180.0)

    def test_percentage_over_100_rejected(self):
        self.assertIsNone(sanitize_percentage("140"))
        self.assertEqual(sanitize_percentage("58"), 58.0)

    def test_string_and_float_input_both_work(self):
        self.assertEqual(sanitize_range(180, 145.0, 215.0), 180.0)
        self.assertEqual(sanitize_range("180", 145.0, 215.0), 180.0)


class TestSanitizeFighterDict(unittest.TestCase):
    def test_bad_row_gets_fields_nulled_not_row_rejected(self):
        row = {
            "name": "Caso Ruim",
            "birth_date": "2099-01-01",
            "height_cm": "30",
            "reach_cm": "999",
            "weight_class": "MIDDLEWEIGHT",
            "str_acc_pct": "140",
            "slpm": "50",
            "age_reported": "39",
        }
        clean = sanitize_fighter_dict(row)
        self.assertIsNone(clean["birth_date"])
        self.assertIsNone(clean["height_cm"])
        self.assertIsNone(clean["reach_cm"])
        self.assertEqual(clean["weight_class"], "Middleweight")
        self.assertIsNone(clean["str_acc_pct"])
        self.assertIsNone(clean["slpm"])
        self.assertEqual(clean["age_reported"], 39)  # esse campo era válido, deve sobreviver

    def test_good_row_passes_through_unchanged_in_value(self):
        row = {"name": "Caso Bom", "height_cm": "180", "reach_cm": "185", "weight_class": "welterweight"}
        clean = sanitize_fighter_dict(row)
        self.assertEqual(clean["height_cm"], 180.0)
        self.assertEqual(clean["reach_cm"], 185.0)
        self.assertEqual(clean["weight_class"], "Welterweight")


class TestDescribeSanitization(unittest.TestCase):
    def test_no_false_positive_on_type_conversion(self):
        """Regressão: string '180' vs float 180.0 não deve aparecer como mudança."""
        before = {"height_cm": "180", "name": "X"}
        after = sanitize_fighter_dict(before)
        descriptions = describe_sanitization(before, after)
        self.assertNotIn("height_cm", " ".join(descriptions))

    def test_discarded_field_is_labeled_correctly(self):
        before = {"birth_date": "2099-01-01"}
        after = sanitize_fighter_dict(before)
        descriptions = describe_sanitization(before, after)
        self.assertTrue(any("descartado" in d for d in descriptions))

    def test_normalized_field_is_labeled_correctly(self):
        before = {"weight_class": "middleweight"}
        after = sanitize_fighter_dict(before)
        descriptions = describe_sanitization(before, after)
        self.assertTrue(any("normalizado" in d for d in descriptions))


if __name__ == "__main__":
    unittest.main()
