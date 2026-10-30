import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from supplier_otd import load_orders, percentile, score, write_report


def row(i, supplier="A", promised="2026-01-10", delivered="2026-01-10"):
    return {"order_id": str(i), "supplier": supplier, "ordered_at": date(2026, 1, 1),
            "promised_at": date.fromisoformat(promised),
            "delivered_at": date.fromisoformat(delivered) if delivered else None}


class ScorecardTests(unittest.TestCase):
    def test_due_date_boundary_is_on_time(self):
        result = score([row(1), row(2, delivered="2026-01-11")], min_deliveries=1)
        self.assertEqual(result["overall_on_time_rate"], .5)
        self.assertEqual(result["suppliers"][0]["median_delay_days"], 0)

    def test_open_orders_count_but_are_excluded_from_rate(self):
        result = score([row(1), row(2, delivered="")])
        self.assertEqual((result["orders"], result["delivered"], result["open"]), (2, 1, 1))
        self.assertEqual(result["overall_on_time_rate"], 1)

    def test_no_deliveries_has_no_fabricated_rate(self):
        result = score([row(1, delivered="")])
        self.assertIsNone(result["overall_on_time_rate"])
        self.assertEqual(result["suppliers"][0]["status"], "insufficient")

    def test_minimum_sample_suppresses_watch_flag(self):
        result = score([row(i, "A") for i in range(10)] + [row(i+20, "B", delivered="2026-01-20") for i in range(10)], min_deliveries=11)
        self.assertEqual([s["status"] for s in result["suppliers"]], ["insufficient", "insufficient"])

    def test_watch_uses_gap_to_overall_rate(self):
        rows = [row(i, "Fast") for i in range(30)] + [row(i+50, "Late", delivered="2026-01-20") for i in range(30)]
        result = score(rows, min_deliveries=20)
        self.assertEqual({s["supplier"]: s["status"] for s in result["suppliers"]}, {"Fast": "ok", "Late": "watch"})

    def test_nearest_rank_percentiles(self):
        self.assertEqual(percentile([10, 1, 4, 2], .5), 2)
        self.assertEqual(percentile([10, 1, 4, 2], .9), 10)
        self.assertIsNone(percentile([], .9))

    def test_duplicate_order_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "in.csv"
            path.write_text("order_id,supplier,ordered_at,promised_at,delivered_at\n1,A,2026-01-01,2026-01-02,\n1,A,2026-01-01,2026-01-02,\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dupliquée"):
                load_orders(path)

    def test_bad_date_and_promise_before_order_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "in.csv"
            path.write_text("order_id,supplier,ordered_at,promised_at,delivered_at\n1,A,01-01-2026,2026-01-02,\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "date ISO"):
                load_orders(path)
            path.write_text("order_id,supplier,ordered_at,promised_at,delivered_at\n1,A,2026-01-03,2026-01-02,\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "précède"):
                load_orders(path)

    def test_outputs_are_created(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            write_report(score([row(1)]), out)
            self.assertTrue((out / "scorecard.json").exists())
            self.assertIn("Fournisseur", (out / "report.md").read_text(encoding="utf-8"))

    def test_parameters_validated(self):
        with self.assertRaises(ValueError): score([], min_deliveries=0)
        with self.assertRaises(ValueError): score([], watch_gap=2)


if __name__ == "__main__": unittest.main()
