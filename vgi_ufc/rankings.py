"""Parse the official UFC rankings published at ufc.com/rankings.

ufc.com renders rankings as a Drupal view: one ``view-grouping`` per division,
with the champion in the table caption and ranked contenders in table rows.
The page also repeats the divisions in a second "meta" view, which is
ignored. Parsing uses only the standard-library HTML parser and fails loudly
when the expected structure disappears instead of returning silent garbage.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

import pyarrow as pa

from vgi_ufc.meta import field

RANKINGS_SCHEMA = pa.schema(
    [
        field(
            "division",
            pa.string(),
            "Division name, for example Lightweight or Men's Pound-for-Pound.",
            nullable=False,
        ),
        field(
            "division_order",
            pa.int32(),
            "Display order of the division on ufc.com (1 = men's pound-for-pound).",
        ),
        field("gender", pa.string(), "men or women."),
        field(
            "pound_for_pound",
            pa.bool_(),
            "Whether this is a pound-for-pound list rather than a weight class.",
        ),
        field(
            "rank",
            pa.int32(),
            "Ordinal rank position (0 = champion, 1-15 contenders); ties share a rank.",
        ),
        field("is_champion", pa.bool_(), "Whether the fighter holds the division title."),
        field("is_interim_champion", pa.bool_(), "Whether the title shown is an interim title."),
        field("fighter_name", pa.string(), "Fighter's name as shown on ufc.com."),
        field("fighter_slug", pa.string(), "ufc.com athlete slug, stable within ufc.com.", nullable=False),
        field("ufc_athlete_url", pa.string(), "Fighter's ufc.com athlete page."),
        field(
            "rank_change",
            pa.int32(),
            "Places gained (positive) or lost (negative) since the previous update.",
        ),
        field(
            "newly_ranked", pa.bool_(), "Whether ufc.com marks the fighter as newly ranked (previously NR)."
        ),
    ]
)

_PRIMARY_VIEW = "view-display-id-block_1"
_WHITESPACE = re.compile(r"\s+")


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


class _RankingsParser(HTMLParser):
    """Collect divisions, champions, and ranked rows from the primary view."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.divisions: list[dict[str, Any]] = []
        self._view_depth = 0
        self._in_primary = False
        self._done = False
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._in_caption = False
        self._row: dict[str, Any] | None = None
        self._cell: str | None = None
        self._href: str | None = None

    # Track the primary view by nesting depth of <div> elements.
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div":
            if not self._in_primary and _PRIMARY_VIEW in classes:
                self._in_primary = True
                self._view_depth = 1
                return
            if self._in_primary:
                self._view_depth += 1
                if "view-grouping-header" in classes:
                    self._start_capture("header")
        if not self._in_primary:
            return
        if tag == "caption":
            self._in_caption = True
        elif tag == "h5" and self._in_caption:
            self._start_capture("champion")
        elif tag == "h6" and self._in_caption:
            self._start_capture("title")
        elif tag == "a" and (self._capture in {"champion", "fighter"}):
            self._href = attributes.get("href")
        elif tag == "tr" and not self._in_caption:
            self._row = {}
        elif tag == "td" and self._row is not None:
            if "views-field-weight-class-rank" in classes:
                self._cell = "rank"
            elif "views-field-title" in classes:
                self._cell = "fighter"
            elif "views-field-weight-class-rank-change" in classes:
                self._cell = "change"
            else:
                self._cell = None
            if self._cell:
                self._start_capture(self._cell)
        elif tag == "span" and self._cell == "change":
            span_classes = " ".join(classes)
            if "rank-increase" in span_classes:
                self._row_set("direction", 1)
            elif "rank-decrease" in span_classes:
                self._row_set("direction", -1)
            elif "not-ranked" in span_classes:
                self._row_set("newly_ranked", True)

    def _row_set(self, key: str, value: Any) -> None:
        if self._row is not None:
            self._row[key] = value

    def _start_capture(self, name: str) -> None:
        self._capture = name
        self._buffer = []
        self._href = None

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._done or not self._in_primary:
            return
        if tag == "div":
            if self._capture == "header":
                self._finish_header()
            self._view_depth -= 1
            if self._view_depth == 0:
                self._in_primary = False
                self._done = True
        elif tag == "caption":
            self._in_caption = False
        elif tag == "h5" and self._capture == "champion":
            if self.divisions:
                self.divisions[-1]["champion"] = (_clean("".join(self._buffer)), self._href)
            self._capture = None
        elif tag == "h6" and self._capture == "title":
            if self.divisions:
                self.divisions[-1]["title"] = _clean("".join(self._buffer))
            self._capture = None
        elif tag == "td" and self._row is not None and self._cell:
            value = _clean("".join(self._buffer))
            if self._cell == "rank":
                self._row["rank"] = value
            elif self._cell == "fighter":
                self._row["fighter"] = (value, self._href)
            elif self._cell == "change":
                self._row["change"] = value
            self._cell = None
            self._capture = None
        elif tag == "tr" and self._row is not None:
            if self.divisions and "fighter" in self._row:
                self.divisions[-1]["rows"].append(self._row)
            self._row = None

    def _finish_header(self) -> None:
        name = _clean("".join(self._buffer))
        self._capture = None
        name = re.sub(r"\s*Top Rank$", "", name)
        self.divisions.append({"name": name, "champion": None, "title": None, "rows": []})


def _slug(href: str | None) -> str | None:
    if not href:
        return None
    match = re.search(r"/athlete/([^/?#]+)", href)
    return match.group(1) if match else None


def _url(href: str | None) -> str | None:
    if not href:
        return None
    return href if href.startswith("http") else f"https://www.ufc.com{href}"


def _change(row: dict[str, Any]) -> int | None:
    direction = row.get("direction")
    if direction is None:
        return 0 if not row.get("newly_ranked") else None
    digits = re.search(r"(\d+)", row.get("change") or "")
    return direction * int(digits.group(1)) if digits else None


def parse_rankings(html: str) -> list[dict[str, Any]]:
    """Return one row per ranked fighter (champions as rank 0)."""
    parser = _RankingsParser()
    parser.feed(html)
    parser.close()
    if not parser.divisions:
        raise ValueError("ufc.com rankings page no longer contains the expected rankings view")
    rows: list[dict[str, Any]] = []
    for order, division in enumerate(parser.divisions, start=1):
        name = division["name"]
        p4p = "pound-for-pound" in name.lower()
        gender = "women" if name.lower().startswith("women") else "men"
        base = {"division": name, "division_order": order, "gender": gender, "pound_for_pound": p4p}
        champion = division["champion"]
        if champion and not p4p:
            title = (division["title"] or "").lower()
            slug = _slug(champion[1])
            if slug:
                rows.append(
                    {
                        **base,
                        "rank": 0,
                        "is_champion": True,
                        "is_interim_champion": "interim" in title,
                        "fighter_name": champion[0],
                        "fighter_slug": slug,
                        "ufc_athlete_url": _url(champion[1]),
                        "rank_change": None,
                        "newly_ranked": False,
                    }
                )
        for row in division["rows"]:
            fighter_name, href = row["fighter"]
            slug = _slug(href)
            digits = re.match(r"\d+", row.get("rank") or "")
            if not slug or not digits:
                continue
            rows.append(
                {
                    **base,
                    "rank": int(digits.group(0)),
                    "is_champion": False,
                    "is_interim_champion": False,
                    "fighter_name": fighter_name,
                    "fighter_slug": slug,
                    "ufc_athlete_url": _url(href),
                    "rank_change": _change(row),
                    "newly_ranked": bool(row.get("newly_ranked")),
                }
            )
    return rows
