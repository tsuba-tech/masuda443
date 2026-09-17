import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live
from update import clear_live_overlay_if_covered, confirmed_basis_date

JST = timezone(timedelta(hours=9))


class LiveEntryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 17, 19, 30, tzinfo=JST)
        self.state = live.empty_state("2026-09-17")

    def add(self, *results):
        for result in results:
            self.state = live.apply(self.state, result, "", self.now)
        return live.totals(self.state["entries"])

    def test_hits_count_as_at_bats(self):
        self.assertEqual(self.add("安打", "二塁打"), {"pa": 2, "ab": 2, "hits": 2, "hr": 0})

    def test_home_run_counts_everywhere(self):
        self.assertEqual(self.add("本塁打"), {"pa": 1, "ab": 1, "hits": 1, "hr": 1})

    def test_walks_and_sacrifices_are_not_at_bats(self):
        # 四球・死球・犠打・犠飛は打席には入るが打数には入らない
        self.assertEqual(self.add("四球", "死球", "犠打", "犠飛"),
                         {"pa": 4, "ab": 0, "hits": 0, "hr": 0})

    def test_outs_count_as_at_bats_without_hits(self):
        self.assertEqual(self.add("凡退", "三振", "失策出塁"),
                         {"pa": 3, "ab": 3, "hits": 0, "hr": 0})

    def test_undo_removes_only_the_last_entry(self):
        self.add("安打", "三振")
        self.state = live.apply(self.state, "直前を取り消す", "", self.now)
        self.assertEqual(live.totals(self.state["entries"]), {"pa": 1, "ab": 1, "hits": 1, "hr": 0})

    def test_clear_empties_the_day(self):
        self.add("安打", "安打")
        self.state = live.apply(self.state, "本日分をクリア", "", self.now)
        self.assertEqual(self.state["entries"], [])

    def test_a_new_day_does_not_inherit_yesterday(self):
        self.add("安打", "安打")
        tomorrow = self.now + timedelta(days=1)
        self.state = live.apply(self.state, "三振", "", tomorrow)
        self.assertEqual(self.state["date"], "2026-09-18")
        self.assertEqual(live.totals(self.state["entries"]), {"pa": 1, "ab": 1, "hits": 0, "hr": 0})


class LiveOverlayLifecycleTests(unittest.TestCase):
    def test_confirmed_basis_date_is_the_previous_day(self):
        # 取得元は未明に前日までの試合を反映して生成される
        self.assertEqual(confirmed_basis_date(datetime(2026, 9, 18, 6, 16, tzinfo=JST)), "2026-09-17")
        self.assertEqual(confirmed_basis_date(None), "")

    def _overlay(self, date, entries):
        path = Path(tempfile.mkdtemp()) / "live.json"
        path.write_text(json.dumps({"date": date, "entries": entries}), encoding="utf-8")
        return path

    def test_overlay_is_cleared_once_confirmed_data_catches_up(self):
        path = self._overlay("2026-09-17", [{"result": "安打"}])
        self.assertTrue(clear_live_overlay_if_covered("2026-09-17", path))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["entries"], [])

    def test_overlay_survives_while_confirmed_data_is_behind(self):
        path = self._overlay("2026-09-17", [{"result": "安打"}])
        self.assertFalse(clear_live_overlay_if_covered("2026-09-16", path))
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
