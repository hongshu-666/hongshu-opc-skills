"""Two account questions: Xiaohongshu profile card URL validation and publication-date ordering."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "account_data.py"
spec = importlib.util.spec_from_file_location("account_data", SCRIPT)
account = importlib.util.module_from_spec(spec)
spec.loader.exec_module(account)


class AccountTests(unittest.TestCase):
    def test_xiaohongshu_profile_work_url_accepted(self):
        row = {
            "id": "69ff1750000000002300589a",
            "url": (
                "https://www.xiaohongshu.com/user/profile/65b27154000000000e021774/"
                "69ff1750000000002300589a?xsec_token=ABiiBA2mhjQrSN9Bx6l34msB&xsec_source=pc_user"
            ),
        }
        account.validate(row, "xiaohongshu")

    def test_orders_works_by_publication_date(self):
        rows = {
            key: {"id": key, "published_display": day, "date_kind": "published", "likes_display": lk, "title_reviewed": True}
            for key, day, lk in [("a", "2025-01-01", "100万"), ("b", "2026-01-03", "2万"), ("c", "2026-01-02", "5万")]
        }
        self.assertEqual([r["id"] for r in account.choose({"count": 2}, rows, None, sort_mode="date")], ["b", "c"])
        self.assertEqual([r["id"] for r in account.summary({"count": 2}, rows, {}, sort_mode="likes")["selected_records"]], ["a", "c"])
        self.assertEqual([r["id"] for r in account.summary({"count": 2}, rows, {}, sort_mode="likes", select_mode="date")["selected_records"]], ["c", "b"])
        self.assertEqual([r["id"] for r in account.summary({"count": 2}, rows, {"selected_ids": ["b", "c"]}, sort_mode="likes")["selected_records"]], ["c", "b"])
        mixed = {**rows, "c": {**rows["c"], "published_display": "编辑于 2026-01-02", "date_kind": "edited"}}
        for cnt in (2, 3):
            with self.assertRaisesRegex(ValueError, "publication dates unproven"):
                account.choose({"count": cnt}, mixed, None, sort_mode="date")
        ordered_mixed = account.choose({"count": 2}, mixed, None, sort_mode="order")
        self.assertEqual([r["id"] for r in ordered_mixed], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
