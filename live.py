"""Apply a manually entered plate appearance to live.json.

The site's confirmed numbers come from the nightly scrape. This file holds
only what the site owner types in while watching a game, so it is always a
provisional overlay that the next morning's confirmed data replaces.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
LIVE_PATH = Path(__file__).with_name("live.json")

# 打席結果ごとの加算ルール。公式定義どおり、四球・死球・犠打・犠飛は
# 打席（PA）には数えるが打数（AB）には数えない。
RESULTS: dict[str, dict[str, int]] = {
    "安打":     {"pa": 1, "ab": 1, "hits": 1, "hr": 0},
    "二塁打":   {"pa": 1, "ab": 1, "hits": 1, "hr": 0},
    "三塁打":   {"pa": 1, "ab": 1, "hits": 1, "hr": 0},
    "本塁打":   {"pa": 1, "ab": 1, "hits": 1, "hr": 1},
    "四球":     {"pa": 1, "ab": 0, "hits": 0, "hr": 0},
    "死球":     {"pa": 1, "ab": 0, "hits": 0, "hr": 0},
    "犠打":     {"pa": 1, "ab": 0, "hits": 0, "hr": 0},
    "犠飛":     {"pa": 1, "ab": 0, "hits": 0, "hr": 0},
    "凡退":     {"pa": 1, "ab": 1, "hits": 0, "hr": 0},
    "三振":     {"pa": 1, "ab": 1, "hits": 0, "hr": 0},
    "失策出塁": {"pa": 1, "ab": 1, "hits": 0, "hr": 0},
}


def empty_state(game_date: str, note: str = "") -> dict:
    return {"date": game_date, "note": note, "entries": []}


def load_state(path: Path = LIVE_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty_state("")


def totals(entries: list[dict]) -> dict[str, int]:
    """Sum a day's entries into plate appearances, at-bats, hits and home runs."""
    summary = {"pa": 0, "ab": 0, "hits": 0, "hr": 0}
    for entry in entries:
        rule = RESULTS.get(entry.get("result", ""))
        if not rule:
            continue
        for key, value in rule.items():
            summary[key] += value
    return summary


UNDO = "直前を取り消す"
CLEAR = "本日分をクリア"


def apply(state: dict, command: str, note: str, now: datetime) -> dict:
    """Return the next state for one menu選択 from the shortcut.

    打席結果と取り消し操作を同じ 1 つの入力にまとめてある。こうしないと
    iPhone のショートカット側でメニュー項目ごとに分岐を作る羽目になる。
    """
    game_date = now.strftime("%Y-%m-%d")
    # 日付が変わっていれば前日分は引き継がない
    if state.get("date") != game_date:
        state = empty_state(game_date, note)
    if note:
        state["note"] = note

    if command == CLEAR:
        return empty_state(game_date, note)
    if command == UNDO:
        if state["entries"]:
            state["entries"].pop()
        return state
    if command in RESULTS:
        state["entries"].append({"result": command, "at": now.isoformat(timespec="seconds")})
        return state
    raise SystemExit(f"unknown command: {command}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    now = datetime.now(JST)
    state = apply(load_state(), args.command, args.note, now)
    state["updated"] = now.isoformat(timespec="seconds")
    state["totals"] = totals(state["entries"])
    LIVE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"live.json: {state['totals']} entries={len(state['entries'])}")


if __name__ == "__main__":
    main()
