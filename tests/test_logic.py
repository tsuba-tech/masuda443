import unittest

from update import (
    GameLine, aggregate_games, build_payload, canonical_team, hitting_streak,
    format_innings, parse_innings, parse_last_modified, parse_pitchers,
    parse_standings_games, parse_team_games,
    regulation_pa_for_games, status_for,
)
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def sample_player(pa=392, ab=356, hits=104):
    return {
        "name": "増田 珠", "team": "S", "games": 110, "pa": pa,
        "ab": ab, "hits": hits, "doubles": 11, "triples": 0, "hr": 8,
        "rbi": 35, "walks": 29, "hbp": 3, "strikeouts": 64,
        "stolen_bases": 4, "avg": hits / ab, "obp": .347, "slg": .390,
        "ops": .737,
    }


LEADER = {
    "name": "佐藤 輝明", "team": "阪神", "games": 127, "pa": 542,
    "ab": 476, "hits": 150, "avg": 150 / 476, "recent5_avg": .211, "obp": .393,
    "slg": .618, "ops": 1.011,
}


GAMES = [
    GameLine("09/13", 3, 1, 0, 0, 1),
    GameLine("09/12", 5, 2, 1, 0, 1, doubles=1),
    GameLine("09/10", 4, 1, 0, 0, 0),
    GameLine("09/09", 3, 1, 0, 0, 0),
    GameLine("09/08", 4, 1, 0, 1, 1),
    GameLine("09/05", 3, 0, 0, 1, 0),
    GameLine("09/04", 4, 4, 0, 0, 0),
    GameLine("09/03", 4, 1, 0, 0, 1),
    GameLine("09/01", 4, 1, 0, 0, 0),
    GameLine("08/30", 4, 2, 0, 0, 1),
]


class LogicTests(unittest.TestCase):
    def test_remaining_pa(self):
        self.assertEqual(build_payload(sample_player(392), LEADER, GAMES, 129)["derived"]["remaining_pa"], 51)
        self.assertEqual(build_payload(sample_player(443), LEADER, GAMES, 129)["derived"]["remaining_pa"], 0)
        self.assertEqual(build_payload(sample_player(450), LEADER, GAMES, 129)["derived"]["remaining_pa"], 0)

    def test_adjusted_average(self):
        player = sample_player(pa=430, ab=400, hits=132)
        self.assertAlmostEqual(build_payload(player, LEADER, GAMES, 129)["derived"]["adjusted_avg"], 132 / 413)

    def test_required_plate_appearances_per_remaining_game(self):
        payload = build_payload(sample_player(392), LEADER, GAMES, 129)
        self.assertEqual(payload["team"]["remaining_games"], 14)
        self.assertAlmostEqual(payload["derived"]["required_pa_per_game"], 51 / 14)

    def test_current_regulation_plate_appearances(self):
        self.assertEqual(regulation_pa_for_games(129), 400)
        self.assertEqual(regulation_pa_for_games(143), 443)
        payload = build_payload(sample_player(392), LEADER, GAMES, 129)
        self.assertEqual(payload["derived"]["current_regulation_remaining_pa"], 8)

    def test_parse_team_games(self):
        html = """
        <table><thead><tr><th>#</th><th>球団</th><th>試</th></tr></thead>
        <tbody><tr><td>4</td><td>ヤクルト</td><td>129</td></tr></tbody></table>
        """
        self.assertEqual(parse_team_games(html), 129)

    def test_parse_standings_covers_every_team(self):
        html = """
        <table><thead><tr><th>#</th><th>球団</th><th>試</th></tr></thead>
        <tbody>
        <tr><td>1</td><td>阪神</td><td>131</td></tr>
        <tr><td>2</td><td>横浜DeNA</td><td>130</td></tr>
        <tr><td>4</td><td>ヤクルト</td><td>129</td></tr>
        </tbody></table>
        """
        standings = parse_standings_games(html)
        self.assertEqual(standings["阪神"], 131)
        self.assertEqual(standings["DeNA"], 130)
        self.assertEqual(standings["ヤクルト"], 129)

    def test_canonical_team_handles_notation_differences(self):
        self.assertEqual(canonical_team("東京ヤクルト"), "ヤクルト")
        self.assertEqual(canonical_team("横浜DeNAベイスターズ"), "DeNA")
        self.assertEqual(canonical_team("ＤｅＮＡ"), "DeNA")
        self.assertIsNone(canonical_team("オリックス"))

    def test_leader_team_games_are_carried_into_the_payload(self):
        payload = build_payload(sample_player(392), LEADER, GAMES, 129, 131)
        self.assertEqual(payload["leader"]["team_games_played"], 131)
        self.assertEqual(payload["leader"]["team_remaining_games"], 12)

    def test_leader_team_games_may_be_unknown(self):
        payload = build_payload(sample_player(392), LEADER, GAMES, 129)
        self.assertIsNone(payload["leader"]["team_games_played"])
        self.assertIsNone(payload["leader"]["team_remaining_games"])

    def test_last_five_and_status(self):
        games = [GameLine(f"09/{i:02}", ab, hits, 0, 0, 0) for i, ab, hits in [(5,4,2),(4,4,2),(3,4,2),(2,4,1),(1,3,1)]]
        last5 = aggregate_games(games, 5)
        self.assertAlmostEqual(last5["avg"], 8 / 19)
        self.assertEqual(status_for(last5["avg"]), "god")

    def test_parse_last_modified(self):
        parsed = parse_last_modified("Tue, 15 Sep 2026 18:49:54 GMT")
        self.assertEqual(parsed.astimezone(JST).strftime("%Y-%m-%d %H:%M"), "2026-09-16 03:49")
        self.assertIsNone(parse_last_modified(None))
        self.assertIsNone(parse_last_modified("not a date"))

    def test_fresh_source_is_not_flagged_stale(self):
        recent = datetime.now(JST) - timedelta(hours=20)
        payload = build_payload(sample_player(392), LEADER, GAMES, 129, 131, recent)
        self.assertFalse(payload["source"]["stale"])
        self.assertEqual(payload["source"]["last_modified"], recent.isoformat(timespec="seconds"))

    def test_source_that_stopped_updating_is_flagged(self):
        # 取得自体は成功するのに元データが動かなくなるサイレント故障を拾えること
        stalled = datetime.now(JST) - timedelta(hours=80)
        payload = build_payload(sample_player(392), LEADER, GAMES, 129, 131, stalled)
        self.assertTrue(payload["source"]["stale"])

    def test_unknown_source_time_is_not_flagged_stale(self):
        payload = build_payload(sample_player(392), LEADER, GAMES, 129, 131)
        self.assertIsNone(payload["source"]["last_modified"])
        self.assertFalse(payload["source"]["stale"])

    def test_innings_are_read_as_thirds(self):
        # 投球回は 1/3 単位の分数表記で載る
        self.assertAlmostEqual(parse_innings("137"), 137.0)
        self.assertAlmostEqual(parse_innings("140 2/3"), 140 + 2 / 3)
        self.assertAlmostEqual(parse_innings("163 1/3"), 163 + 1 / 3)
        with self.assertRaises(Exception):
            parse_innings("140 3/3")

    def test_innings_round_trip_back_to_text(self):
        for text in ("137", "140 2/3", "163 1/3"):
            self.assertEqual(format_innings(parse_innings(text)), text)
        # 端数が丸め上がる場合も繰り上げる
        self.assertEqual(format_innings(2 + 2.9999 / 3), "3")

    def test_parse_pitchers_picks_the_tracked_two(self):
        html = """
        <table><thead><tr><th>#</th><th>選手名</th><th>球団</th><th>防御率</th>
        <th>勝利</th><th>敗戦</th><th>奪三振</th><th>試合</th><th>投球回</th></tr></thead>
        <tbody>
        <tr><td>1</td><td>村上 頌樹</td><td>阪神</td><td>1.93</td><td>10</td><td>8</td><td>138</td><td>24</td><td>163 1/3</td></tr>
        <tr><td>5</td><td>山野 太一</td><td>ヤクルト</td><td>2.43</td><td>10</td><td>4</td><td>134</td><td>22</td><td>140 2/3</td></tr>
        <tr><td>8</td><td>奥川 恭伸</td><td>ヤクルト</td><td>2.76</td><td>7</td><td>8</td><td>107</td><td>20</td><td>137</td></tr>
        </tbody></table>
        """
        pitchers = parse_pitchers(html)
        self.assertEqual([p["name"] for p in pitchers], ["奥川 恭伸", "山野 太一"])
        self.assertAlmostEqual(pitchers[1]["innings"], 140 + 2 / 3)

    def test_remaining_innings_are_carried_into_the_payload(self):
        pitchers = [{
            "name": "奥川 恭伸", "team": "ヤクルト", "era": 2.76, "wins": 7, "losses": 8,
            "games": 20, "strikeouts": 107, "innings": 137.0, "innings_text": "137",
        }]
        payload = build_payload(sample_player(392), LEADER, GAMES, 129, 131, None, pitchers)
        self.assertEqual(payload["target_innings"], 143)
        entry = payload["pitchers"][0]
        self.assertAlmostEqual(entry["remaining_innings"], 6.0)
        self.assertEqual(entry["remaining_innings_text"], "6")

    def test_hitting_streak(self):
        self.assertEqual(hitting_streak(GAMES), 5)

if __name__ == "__main__":
    unittest.main()
