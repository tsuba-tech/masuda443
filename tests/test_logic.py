import unittest

from update import GameLine, aggregate_games, build_payload, hitting_streak, parse_team_games, regulation_pa_for_games, status_for


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

    def test_last_five_and_status(self):
        games = [GameLine(f"09/{i:02}", ab, hits, 0, 0, 0) for i, ab, hits in [(5,4,2),(4,4,2),(3,4,2),(2,4,1),(1,3,1)]]
        last5 = aggregate_games(games, 5)
        self.assertAlmostEqual(last5["avg"], 8 / 19)
        self.assertEqual(status_for(last5["avg"]), "god")

    def test_hitting_streak(self):
        self.assertEqual(hitting_streak(GAMES), 5)

if __name__ == "__main__":
    unittest.main()
