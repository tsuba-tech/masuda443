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
import unicodedata
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag


# 取得元が更新されなくなったと判断するまでの時間。
# 月曜など試合のない日をまたいでも誤検知しないよう、丸3日に余裕を持たせている。
SOURCE_STALE_HOURS = 72

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


@dataclass(frozen=True)
class FetchedPage:
    """A fetched page body plus the source server's own Last-Modified time."""

    text: str
    last_modified: datetime | None


def parse_last_modified(raw: str | None) -> datetime | None:
    """Parse an HTTP Last-Modified header into JST, or None when absent/invalid."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(JST)
    except (TypeError, ValueError):
        return None


def fetch(session: requests.Session, url: str) -> FetchedPage:
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
            return FetchedPage(text, parse_last_modified(response.headers.get("Last-Modified")))
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


# 順位表と打撃成績表で球団名の表記が違う（「ヤクルト」「東京ヤクルト」など）ため、
# どちらの表記から来てもひとつのキーに寄せられるようにしておく。
CENTRAL_TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "ヤクルト": ("ヤクルト", "東京ヤクルト", "東京ヤクルトスワローズ", "ヤ"),
    "阪神": ("阪神", "阪神タイガース", "神"),
    "巨人": ("巨人", "読売", "読売ジャイアンツ", "巨"),
    "広島": ("広島", "広島東洋", "広島東洋カープ", "広"),
    "中日": ("中日", "中日ドラゴンズ", "中"),
    "DeNA": ("DENA", "横浜DENA", "横浜DENAベイスターズ", "横浜", "デ"),
}


def canonical_team(label: str) -> str | None:
    """Map a team label from any table onto a canonical Central League key."""
    text = unicodedata.normalize("NFKC", normalize(label)).upper()
    if not text:
        return None
    for canonical, aliases in CENTRAL_TEAM_ALIASES.items():
        if text in aliases:
            return canonical
    # 「横浜DeNAベイスターズ」のような表記ゆれは部分一致で拾う（1文字略称は誤爆するので除く）
    for canonical, aliases in CENTRAL_TEAM_ALIASES.items():
        if any(len(alias) >= 2 and alias in text for alias in aliases):
            return canonical
    return None


def parse_standings_games(html: str) -> dict[str, int]:
    """Return completed game counts for every Central League team, keyed by canonical name."""
    soup = BeautifulSoup(html, "html.parser")
    table = find_rank_table(soup, ["球団", "試"])
    standings: dict[str, int] = {}
    for row, _ in rows_as_dicts(table):
        team = canonical_team(pick(row, "球団"))
        if team and team not in standings:
            standings[team] = as_int(pick(row, "試", "試合"), f"{team} team games")
    if not standings:
        raise UpdateError("no Central League teams were found in the standings")
    return standings


def parse_team_games(html: str) -> int:
    """Return the Swallows' completed team games from the league standings."""
    standings = parse_standings_games(html)
    if "ヤクルト" not in standings:
        raise UpdateError("Yakult was not found in the Central League standings")
    return standings["ヤクルト"]


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


def fetch_masuda_stats(session: requests.Session) -> tuple[dict, str, datetime | None]:
    """Fetch the season line and return it with the player URL and the source's update time."""
    page = fetch(session, MASUDA_URL)
    masuda, player_url = parse_masuda(page.text)
    return masuda, player_url, page.last_modified


def fetch_leader_stats(session: requests.Session) -> tuple[dict, datetime | None]:
    """Fetch the current qualified Central League batting leader."""
    page = fetch(session, LEADER_URL)
    return parse_leader(page.text), page.last_modified


def fetch_standings(session: requests.Session) -> tuple[dict[str, int], datetime | None]:
    """Fetch completed game counts for every Central League team in one request."""
    page = fetch(session, TEAM_STANDINGS_URL)
    return parse_standings_games(page.text), page.last_modified


def fetch_recent_stats(
    session: requests.Session, player_url: str
) -> tuple[list[GameLine], datetime | None]:
    """Fetch only Masuda's plate-appearance page and aggregate it later."""
    plate_url = player_url.replace(".html", "S.html")
    page = fetch(session, plate_url)
    return parse_recent_games(page.text), page.last_modified


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


def regulation_pa_for_games(games: int) -> int:
    """NPB regulation plate appearances: team games × 3.1, rounded half up."""
    return int(games * 3.1 + 0.5)


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


def build_payload(
    masuda: dict,
    leader: dict,
    games: list[GameLine],
    team_games_played: int,
    leader_team_games_played: int | None = None,
    source_last_modified: datetime | None = None,
) -> dict:
    remaining = max(TARGET_PA - masuda["pa"], 0)
    remaining_games = max(SEASON_GAMES - team_games_played, 0)
    current_regulation_pa = regulation_pa_for_games(team_games_played)
    adjusted_avg = (
        masuda["hits"] / (masuda["ab"] + remaining)
        if remaining
        else masuda["avg"]
    )
    last5 = aggregate_games(games, 5)
    last10 = aggregate_games(games, 10)
    streak = hitting_streak(games)
    status = status_for(last5["avg"])
    now = datetime.now(JST)
    fetched_at = now.isoformat(timespec="seconds")
    # 取得自体は成功しているのに取得元が更新されなくなっている状態を拾う。
    # 元は毎日未明に生成されるので、丸3日動かなければ明らかに異常とみなす。
    source_age_hours = (
        (now - source_last_modified).total_seconds() / 3600
        if source_last_modified is not None
        else None
    )
    source_stale = source_age_hours is not None and source_age_hours > SOURCE_STALE_HOURS
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
            "current_regulation_pa": current_regulation_pa,
        },
        "source": {
            "site": "baseballdata.jp",
            "site_name": "データで楽しむプロ野球",
            "last_modified": (
                source_last_modified.isoformat(timespec="seconds")
                if source_last_modified is not None
                else None
            ),
            "stale": source_stale,
            "masuda": MASUDA_URL,
            "leader": LEADER_URL,
            "team_standings": TEAM_STANDINGS_URL,
        },
        "masuda": masuda,
        # 首位打者の残り試合数は所属球団の順位表の行から取る（増田選手側と同じ出典）
        "leader": {
            **leader,
            "team_games_played": leader_team_games_played,
            "team_remaining_games": (
                max(SEASON_GAMES - leader_team_games_played, 0)
                if leader_team_games_played is not None
                else None
            ),
        },
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
            "current_regulation_remaining_pa": max(current_regulation_pa - masuda["pa"], 0),
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
        masuda, player_url, masuda_modified = fetch_masuda_stats(session)
        assert_robots_allowed(robots, [player_url.replace(".html", "S.html")])
        leader, leader_modified = fetch_leader_stats(session)
        standings, standings_modified = fetch_standings(session)
        if "ヤクルト" not in standings:
            raise UpdateError("Yakult was not found in the Central League standings")
        team_games_played = standings["ヤクルト"]
        leader_team = canonical_team(leader.get("team", ""))
        leader_team_games_played = standings.get(leader_team) if leader_team else None
        if leader_team_games_played is None:
            LOG.warning("leader team %r was not found in the standings; "
                        "the pace comparison will fall back to the player's game count",
                        leader.get("team"))
        games, games_modified = fetch_recent_stats(session, player_url)
        # 取得元は全ページを深夜バッチで一括生成するため、最も新しい Last-Modified を代表値にする
        modified_times = [
            t for t in (masuda_modified, leader_modified, standings_modified, games_modified)
            if t is not None
        ]
        source_last_modified = max(modified_times) if modified_times else None
        validate(masuda, leader, games, team_games_played)
        payload = build_payload(
            masuda, leader, games, team_games_played,
            leader_team_games_played, source_last_modified,
        )
        if payload["source"]["stale"]:
            # 取得は成功しているので更新自体は止めない。気づけるように警告だけ残す。
            LOG.warning("source has not changed for over %s hours (last modified %s); "
                        "the site will show a stale-data notice",
                        SOURCE_STALE_HOURS, source_last_modified)
            print(f"::warning::source data appears stale (last modified {source_last_modified})")
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
