"""Fetch MASUDA 443 data and atomically update data.json.

The parser intentionally discovers columns from the page headers instead of
depending on a hard-coded table position.  If fetching, parsing, or validation
fails, the existing data.json is left untouched.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://baseballdata.jp/"
MASUDA_URL = urljoin(BASE_URL, "cdrm.html")
LEADER_URL = urljoin(BASE_URL, "ctop.html")
TEAM_STANDINGS_URL = urljoin(BASE_URL, "c/")
TARGET_PA = 443
SEASON_GAMES = 143
PLAYER_NAME = "増田珠"
JST = timezone(timedelta(hours=9))
OUTPUT_PATH = Path(__file__).with_name("data.json")
STATUS_PATH = Path(__file__).with_name("fetch-status.json")
AVG_TOLERANCE = 0.002
MAX_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 3
USER_AGENT = os.getenv(
    "MASUDA443_USER_AGENT",
    "MASUDA443-FanSite/1.0 (+https://github.com/)",
)

LOG = logging.getLogger("masuda443")


class UpdateError(RuntimeError):
    """Raised when source data is missing, malformed, or implausible."""


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def as_int(value: str, label: str) -> int:
    cleaned = normalize(value).replace(",", "")
    if not re.fullmatch(r"-?\d+", cleaned):
        raise UpdateError(f"{label} is not an integer: {value!r}")
    return int(cleaned)


def as_float(value: str, label: str) -> float:
    cleaned = normalize(value)
    if cleaned.startswith("."):
        cleaned = "0" + cleaned
    try:
        return float(cleaned)
    except ValueError as exc:
        raise UpdateError(f"{label} is not numeric: {value!r}") from exc


def fetch(session: requests.Session, url: str) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            LOG.info("fetching %s (attempt %s/%s)", url, attempt, MAX_ATTEMPTS)
            response = session.get(url, timeout=(10, 30))
            if response.status_code in {403, 429}:
                raise UpdateError(f"HTTP {response.status_code}; refusing to retry: {url}")
            response.raise_for_status()
            try:
                text = response.content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise UpdateError(f"response was not valid UTF-8: {url}") from exc
            if len(text) < 1000:
                raise UpdateError(f"response was unexpectedly short: {url}")
            return text
        except UpdateError:
            raise
        except requests.RequestException:
            if attempt >= MAX_ATTEMPTS:
                raise
            LOG.warning("request failed; waiting %s seconds before one retry", RETRY_DELAY_SECONDS)
            time.sleep(RETRY_DELAY_SECONDS)
    raise UpdateError(f"unreachable fetch failure: {url}")


def load_robots(session: requests.Session) -> RobotFileParser:
    robots_url = urljoin(BASE_URL, "robots.txt")
    LOG.info("checking %s", robots_url)
    response = session.get(robots_url, timeout=(10, 30))
    if response.status_code in {403, 429}:
        raise UpdateError(f"robots.txt returned HTTP {response.status_code}")
    response.raise_for_status()
    robots = RobotFileParser()
    robots.set_url(robots_url)
    robots.parse(response.content.decode("utf-8-sig").splitlines())
    return robots


def assert_robots_allowed(robots: RobotFileParser, urls: Iterable[str]) -> None:
    blocked = [url for url in urls if not robots.can_fetch(USER_AGENT, url)]
    if blocked:
        raise UpdateError(f"robots.txt disallows required path(s): {', '.join(blocked)}")


def find_rank_table(soup: BeautifulSoup, required_headers: Iterable[str]) -> Tag:
    required = {normalize(value) for value in required_headers}
    for table in soup.find_all("table"):
        header_cells = table.select("thead th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all(["th", "td"]) if first_row else []
        headers = {normalize(cell.get_text(" ", strip=True)) for cell in header_cells}
        if required.issubset(headers):
            return table
    raise UpdateError(f"table with headers {sorted(required)} was not found")


def table_headers(table: Tag) -> list[str]:
    cells = table.select("thead tr:last-child th")
    if not cells:
        row = table.find("tr")
        cells = row.find_all(["th", "td"]) if row else []
    return [normalize(cell.get_text(" ", strip=True)) or "順位" for cell in cells]


def rows_as_dicts(table: Tag) -> list[tuple[dict[str, str], Tag]]:
    headers = table_headers(table)
    rows: list[tuple[dict[str, str], Tag]] = []
    body_rows = table.select("tbody tr") or table.find_all("tr")[1:]
    for row in body_rows:
        cells = row.find_all("td", recursive=False)
        if len(cells) != len(headers):
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells]
        rows.append((dict(zip(headers, values)), row))
    return rows


def pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        key = normalize(name)
        if key in row:
            return row[key]
    raise UpdateError(f"none of the columns exist: {', '.join(names)}")


def parse_masuda(html: str) -> tuple[dict, str]:
    soup = BeautifulSoup(html, "html.parser")
    table = find_rank_table(soup, ["選手", "打率", "試合", "打席", "打数", "安打"])
    for row, element in rows_as_dicts(table):
        if normalize(pick(row, "選手")) != PLAYER_NAME:
            continue
        player_link = element.select_one("td.player-col a, a[href*='playerB/']")
        if not player_link or not player_link.get("href"):
            raise UpdateError("Masuda player detail link was not found")
        hits = as_int(pick(row, "安打"), "Masuda hits")
        ab = as_int(pick(row, "打数"), "Masuda AB")
        displayed_avg = as_float(pick(row, "打率"), "Masuda average")
        calculated_avg = hits / ab if ab else 0.0
        if abs(displayed_avg - calculated_avg) > AVG_TOLERANCE:
            raise UpdateError(
                f"Masuda average mismatch: displayed={displayed_avg}, calculated={calculated_avg}"
            )
        masuda = {
            "name": "増田 珠",
            "team": "S",
            "games": as_int(pick(row, "試合"), "Masuda games"),
            "pa": as_int(pick(row, "打席"), "Masuda PA"),
            "ab": ab,
            "hits": hits,
            "doubles": as_int(pick(row, "二塁打"), "Masuda doubles"),
            "triples": as_int(pick(row, "三塁打"), "Masuda triples"),
            "hr": as_int(pick(row, "本塁打"), "Masuda HR"),
            "rbi": as_int(pick(row, "打点"), "Masuda RBI"),
            "walks": as_int(pick(row, "四球"), "Masuda walks"),
            "hbp": as_int(pick(row, "死球"), "Masuda HBP"),
            "strikeouts": as_int(pick(row, "三振"), "Masuda strikeouts"),
            "stolen_bases": as_int(pick(row, "盗塁"), "Masuda stolen bases"),
            "avg": calculated_avg,
            "obp": as_float(pick(row, "出塁率"), "Masuda OBP"),
            "slg": as_float(pick(row, "長打率"), "Masuda SLG"),
            "ops": as_float(pick(row, "OPS"), "Masuda OPS"),
        }
        return masuda, urljoin(BASE_URL, player_link["href"])
    raise UpdateError("増田珠 was not found in the non-qualified rankings")


def parse_leader(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = find_rank_table(soup, ["選手名", "球団", "打率", "試合", "打席", "打数", "安打"])
    rows = rows_as_dicts(table)
    if not rows:
        raise UpdateError("qualified batting rankings contained no players")
    row, _ = rows[0]
    hits = as_int(pick(row, "安打"), "leader hits")
    ab = as_int(pick(row, "打数"), "leader AB")
    displayed_avg = as_float(pick(row, "打率"), "leader average")
    calculated_avg = hits / ab if ab else 0.0
    if abs(displayed_avg - calculated_avg) > AVG_TOLERANCE:
        raise UpdateError(
            f"leader average mismatch: displayed={displayed_avg}, calculated={calculated_avg}"
        )
    team_text = pick(row, "球団")
    return {
        "name": pick(row, "選手名", "選手"),
        "team": team_text,
        "games": as_int(pick(row, "試合"), "leader games"),
        "pa": as_int(pick(row, "打席"), "leader PA"),
        "ab": ab,
        "hits": hits,
        "avg": calculated_avg,
        "recent5_avg": as_float(pick(row, "最近5試合"), "leader recent-5 average"),
        "obp": as_float(pick(row, "出塁率"), "leader OBP"),
        "slg": as_float(pick(row, "長打率"), "leader SLG"),
        "ops": as_float(pick(row, "OPS"), "leader OPS"),
    }


def parse_team_games(html: str) -> int:
    """Return the Swallows' completed team games from the league standings."""
    soup = BeautifulSoup(html, "html.parser")
    table = find_rank_table(soup, ["球団", "試"])
    for row, _ in rows_as_dicts(table):
        if normalize(pick(row, "球団")) in {"ヤクルト", "東京ヤクルト"}:
            return as_int(pick(row, "試", "試合"), "Swallows team games")
    raise UpdateError("Yakult was not found in the Central League standings")


@dataclass
class GameLine:
    date: str
    ab: int
    hits: int
    hr: int
    walks_hbp: int
    strikeouts: int
    doubles: int = 0
    triples: int = 0


def parse_recent_games(html: str) -> list[GameLine]:
    soup = BeautifulSoup(html, "html.parser")
    table = find_rank_table(soup, ["月日", "打数", "安", "本", "四死", "三振", "結果"])
    headers = table_headers(table)
    games: list[GameLine] = []
    current: GameLine | None = None
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) != len(headers):
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells]
        item = dict(zip(headers, values))
        date = normalize(item.get("月日", ""))
        if re.fullmatch(r"\d{2}/\d{2}", date):
            current = GameLine(
                date=date,
                ab=as_int(item["打数"], f"{date} AB"),
                hits=as_int(item["安"], f"{date} hits"),
                hr=as_int(item["本"], f"{date} HR"),
                walks_hbp=as_int(item["四死"], f"{date} walks/HBP"),
                strikeouts=as_int(item["三振"], f"{date} strikeouts"),
            )
            games.append(current)
        if current is None:
            continue
        result = normalize(item.get("結果", ""))
        if "２" in result or "2塁打" in result or "二塁打" in result:
            current.doubles += 1
        if "３" in result or "3塁打" in result or "三塁打" in result:
            current.triples += 1
    if not games:
        raise UpdateError("no dated game rows were found in the all-plate-appearances table")
    return games


def fetch_masuda_stats(session: requests.Session) -> tuple[dict, str]:
    """Fetch the season line and return it with the discovered player URL."""
    return parse_masuda(fetch(session, MASUDA_URL))


def fetch_leader_stats(session: requests.Session) -> dict:
    """Fetch the current qualified Central League batting leader."""
    return parse_leader(fetch(session, LEADER_URL))


def fetch_team_games(session: requests.Session) -> int:
    """Fetch the Swallows' completed team-game count."""
    return parse_team_games(fetch(session, TEAM_STANDINGS_URL))


def fetch_recent_stats(session: requests.Session, player_url: str) -> list[GameLine]:
    """Fetch only Masuda's plate-appearance page and aggregate it later."""
    plate_url = player_url.replace(".html", "S.html")
    return parse_recent_games(fetch(session, plate_url))


def aggregate_games(games: list[GameLine], count: int) -> dict:
    chosen = games[:count]
    if not chosen:
        raise UpdateError("cannot aggregate an empty game list")
    total_ab = sum(game.ab for game in chosen)
    total_hits = sum(game.hits for game in chosen)
    return {
        "games": len(chosen),
        "ab": total_ab,
        "hits": total_hits,
        "doubles": sum(game.doubles for game in chosen),
        "triples": sum(game.triples for game in chosen),
        "hr": sum(game.hr for game in chosen),
        "walks_hbp": sum(game.walks_hbp for game in chosen),
        "strikeouts": sum(game.strikeouts for game in chosen),
        "avg": total_hits / total_ab if total_ab else 0.0,
    }


def hitting_streak(games: list[GameLine]) -> int:
    streak = 0
    for game in games:
        if game.hits <= 0:
            break
        streak += 1
    return streak


def status_for(avg: float) -> str:
    if avg >= 0.400:
        return "god"
    if avg >= 0.300:
        return "hot"
    if avg >= 0.220:
        return "normal"
    return "cold"


def validate(masuda: dict, leader: dict, games: list[GameLine], team_games_played: int) -> None:
    problems: list[str] = []
    if masuda["pa"] <= 0:
        problems.append("Masuda PA must be positive")
    if masuda["ab"] <= 0:
        problems.append("Masuda AB must be positive")
    if not 0 <= masuda["hits"] <= masuda["ab"]:
        problems.append("Masuda hits must be between 0 and AB")
    if masuda["pa"] < masuda["ab"]:
        problems.append("Masuda PA must not be below AB")
    if not 0.100 < masuda["avg"] < 0.500:
        problems.append("Masuda average is outside the expected range")
    if leader["ab"] <= 100:
        problems.append("leader AB must exceed 100")
    if not 0.200 < leader["avg"] < 0.500:
        problems.append("leader average is outside the expected range")
    if len(games) < 5:
        problems.append("fewer than five recent games were found")
    if not 0 <= team_games_played <= SEASON_GAMES:
        problems.append("Swallows team games are outside the expected range")
    if problems:
        raise UpdateError("; ".join(problems))


def build_payload(masuda: dict, leader: dict, games: list[GameLine], team_games_played: int) -> dict:
    remaining = max(TARGET_PA - masuda["pa"], 0)
    remaining_games = max(SEASON_GAMES - team_games_played, 0)
    adjusted_avg = (
        masuda["hits"] / (masuda["ab"] + remaining)
        if remaining
        else masuda["avg"]
    )
    last5 = aggregate_games(games, 5)
    last10 = aggregate_games(games, 10)
    streak = hitting_streak(games)
    status = status_for(last5["avg"])
    fetched_at = datetime.now(JST).isoformat(timespec="seconds")
    return {
        "updated": fetched_at,
        "source_status": "ok",
        "last_successful_fetch": fetched_at,
        "target_pa": TARGET_PA,
        "team": {
            "name": "東京ヤクルトスワローズ",
            "season_games": SEASON_GAMES,
            "games_played": team_games_played,
            "remaining_games": remaining_games,
        },
        "source": {
            "site": "baseballdata.jp",
            "masuda": MASUDA_URL,
            "leader": LEADER_URL,
            "team_standings": TEAM_STANDINGS_URL,
        },
        "masuda": masuda,
        "leader": leader,
        "recent": {
            "last5": last5,
            "last10": last10,
            "hit_streak": streak,
            "latest_game": {
                "date": games[0].date,
                "hits": games[0].hits,
                "hr": games[0].hr,
                "multi_hit_3": games[0].hits >= 3,
            },
        },
        "derived": {
            "remaining_pa": remaining,
            "required_pa_per_game": remaining / remaining_games if remaining_games else None,
            "progress": min(masuda["pa"] / TARGET_PA * 100, 100),
            "avg_gap": max(leader["avg"] - masuda["avg"], 0),
            "adjusted_avg": adjusted_avg,
            "adjusted_gap": leader["avg"] - adjusted_avg,
            "status": status,
        },
    }


def atomic_write(payload: dict, path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="data-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if os.getenv("SCRAPING_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        LOG.warning("SCRAPING_ENABLED=false; external requests and data.json update are disabled")
        atomic_write({
            "source_status": "disabled",
            "attempted": datetime.now(JST).isoformat(timespec="seconds"),
        }, STATUS_PATH)
        return
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        # Only the required data pages are fetched; this script never crawls the site.
        robots = load_robots(session)
        assert_robots_allowed(robots, [MASUDA_URL, LEADER_URL, TEAM_STANDINGS_URL])
        masuda, player_url = fetch_masuda_stats(session)
        assert_robots_allowed(robots, [player_url.replace(".html", "S.html")])
        leader = fetch_leader_stats(session)
        team_games_played = fetch_team_games(session)
        games = fetch_recent_stats(session, player_url)
        validate(masuda, leader, games, team_games_played)
        payload = build_payload(masuda, leader, games, team_games_played)
        atomic_write(payload)
        atomic_write({
            "source_status": "ok",
            "attempted": payload["updated"],
            "last_successful_fetch": payload["last_successful_fetch"],
        }, STATUS_PATH)
    except Exception as exc:
        atomic_write({
            "source_status": "error",
            "attempted": datetime.now(JST).isoformat(timespec="seconds"),
            "message": type(exc).__name__,
        }, STATUS_PATH)
        LOG.exception("update failed; existing data.json was not changed")
        raise
    LOG.info(
        "updated %s: PA=%s AVG=%.6f leader=%s %.6f",
        OUTPUT_PATH,
        masuda["pa"],
        masuda["avg"],
        leader["name"],
        leader["avg"],
    )


if __name__ == "__main__":
    main()
