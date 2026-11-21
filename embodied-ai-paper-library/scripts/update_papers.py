"""Refresh the site's arXiv and Crossref paper metadata."""

import argparse
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import crossref


ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://export.arxiv.org/api/query"
SOURCE_URL = "https://arxiv.org/"
LOOKBACK_DAYS = 90
MAX_RESULTS = 200
MAX_COOPERATION_RESULTS = 100
MAX_FEED_BYTES = 8 * 1024 * 1024

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}
ARXIV_ID = re.compile(
    r"https?://(?:export\.)?arxiv\.org/abs/"
    r"(?P<id>\d{4}\.\d{4,5}|[a-zA-Z0-9.-]+/\d{7})(?:v(?P<version>\d+))?"
)

METHOD_TERMS = (
    "vision language action",
    "VLA",
    "world action model",
    "world action models",
    "WAM",
    "world model",
    "world models",
)
DOMAIN_TERMS = (
    "driving",
    "autonomous vehicle",
    "autonomous vehicles",
    "driverless",
    "robot",
    "robots",
    "robotic",
    "robotics",
    "embodied",
)
COOPERATION_TERMS = (
    "unmanned ground vehicles",
    "unmanned ground vehicle",
    "uncrewed ground vehicles",
    "ground robots",
    "UGV",
    "UGVs",
    "wheeled mobile robots",
    "automated guided vehicles",
    "vehicle platoon",
    "vehicle platooning",
    "platooning",
    "multi robot",
    "multi agent cooperative control",
)
METHOD_PATTERNS = {
    "VLA": re.compile(r"\bvision[-\s]+language[-\s]+action\b|\bVLAs?\b", re.IGNORECASE),
    "WAM": re.compile(
        r"\bworld[-\s]+action[-\s]+models?\b|\bWAMs?\s+(?:models?|framework|architecture)\b",
        re.IGNORECASE,
    ),
    "WM": re.compile(r"\bworld[-\s]+model(?:s|ing|ling)?\b", re.IGNORECASE),
}
DOMAIN_PATTERNS = {
    "driving": re.compile(
        r"\b(?:autonomous[-\s]+(?:driving|vehicles?|cars?|trucks?)|self[-\s]+driving"
        r"|automated[-\s]+driving|driverless|end[-\s]+to[-\s]+end[-\s]+driving"
        r"|driving[-\s]+(?:polic(?:y|ies)|agents?|planners?))\b",
        re.IGNORECASE,
    ),
    "robotics": re.compile(
        r"\b(?:robots?|robotic(?:s|ally)?|embodied[-\s]+(?:ai|agents?|intelligence"
        r"|manipulation|navigation|control|polic(?:y|ies)))\b",
        re.IGNORECASE,
    ),
}
GROUND_PATTERN = re.compile(
    r"\b(?:ground[-\s]+(?:vehicles?|robots?)|UGVs?|(?:multi[-\s]+)?AGVs?"
    r"|automated[-\s]+guided[-\s]+vehicles?|wheeled[-\s]+(?:mobile[-\s]+)?robots?)\b",
    re.IGNORECASE,
)
ROAD_PATTERN = re.compile(
    r"\b(?:vehicle|truck|car|highway|traffic)[-\s]+platoons?(?:ing)?\b"
    r"|\bplatooning\b.{0,60}\b(?:vehicles?|trucks?|cars?|highways?|traffic)\b"
    r"|\bcooperative[-\s]+adaptive[-\s]+cruise[-\s]+control\b",
    re.IGNORECASE,
)
MULTI_ROBOT_PATTERN = re.compile(
    r"\b(?:multi[-\s]*robots?|multiple[-\s]+(?:mobile[-\s]+)?robots?"
    r"|teams?[-\s]+of[-\s]+robots?|robot[-\s]+(?:teams?|swarms?|fleets?)"
    r"|(?:teams?|swarms?|fleets?)[-\s]+of[-\s]+(?:mobile[-\s]+)?robots?)\b",
    re.IGNORECASE,
)
MULTI_AGENT_PATTERN = re.compile(
    r"\b(?:multi[-\s]*(?:agents?|vehicles?|UGVs?|AGVs?)"
    r"|multiple[-\s]+(?:ground[-\s]+)?vehicles?|formation|platoons?|platooning)\b",
    re.IGNORECASE,
)
COOPERATION_PATTERN = re.compile(
    r"\b(?:formation|platoons?|platooning|consensus|coordination|cooperation"
    r"|(?:cooperative|collaborative|distributed|decentralized)[-\s]+"
    r"(?:tracking|path|trajectory|navigation|control|planning|decision|learning))\b",
    re.IGNORECASE,
)
COOPERATION_TITLE_PATTERN = re.compile(
    r"\b(?:swarms?|swarming|teams?|cooperative|collaborative|distributed|decentralized"
    r"|consensus|formations?|platoons?|platooning|coordination|coordinated|cooperation)\b",
    re.IGNORECASE,
)
NON_GROUND_PATTERN = re.compile(r"\b(?:UAVs?|aerial|marine|underwater|quadrotors?)\b", re.IGNORECASE)
DASHES = str.maketrans({dash: "-" for dash in "‐‑‒–—−"})


def search_group(terms):
    return "(" + " OR ".join(f'all:"{term}"' for term in terms) + ")"


def fetch_feed(search, limit):
    query = urlencode({
        "search_query": search,
        "start": 0,
        "max_results": limit,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    request = Request(
        f"{API_URL}?{query}",
        headers={"Accept": "application/atom+xml", "User-Agent": "PaperTracker/1.0"},
    )
    with urlopen(request, timeout=35) as response:
        return response.read(MAX_FEED_BYTES + 1)


def has_cooperation_title(title):
    title = unicodedata.normalize("NFKC", title).translate(DASHES)
    return any(pattern.search(title) for pattern in (
        MULTI_ROBOT_PATTERN, MULTI_AGENT_PATTERN, COOPERATION_TITLE_PATTERN
    ))


def classify(title, abstract):
    match_text = unicodedata.normalize("NFKC", f"{title} {abstract}").translate(DASHES)
    methods = [name for name, pattern in METHOD_PATTERNS.items() if pattern.search(match_text)]
    domains = [name for name, pattern in DOMAIN_PATTERNS.items() if pattern.search(match_text)]
    ground = bool(GROUND_PATTERN.search(match_text))
    road = bool(ROAD_PATTERN.search(match_text))
    multi_robot = bool(MULTI_ROBOT_PATTERN.search(match_text))
    multi_agent = bool(MULTI_AGENT_PATTERN.search(match_text)) or multi_robot
    road_agents = "driving" in domains and multi_agent
    terrestrial_robots = multi_robot and (ground or not NON_GROUND_PATTERN.search(match_text))
    if (
        has_cooperation_title(title)
        and COOPERATION_PATTERN.search(match_text)
        and (road or road_agents or terrestrial_robots or (ground and multi_agent))
    ):
        methods.append("MAS")
        if (road or road_agents) and "driving" not in domains:
            domains.append("driving")
        if (ground or terrestrial_robots) and "robotics" not in domains:
            domains.append("robotics")
    return methods, domains


def atom_text(element, path):
    node = element.find(path, NAMESPACES)
    return "" if node is None else " ".join("".join(node.itertext()).split())


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("arXiv returned a timestamp without a timezone")
    return parsed.astimezone(timezone.utc)


def parse_papers(raw_feed, now):
    if len(raw_feed) > MAX_FEED_BYTES:
        raise ValueError("arXiv feed exceeded the expected response size")
    root = ET.fromstring(raw_feed)
    if root.tag != f"{{{NAMESPACES['atom']}}}feed":
        raise ValueError("arXiv returned something other than an Atom feed")
    entries = root.findall("atom:entry", NAMESPACES)
    total_results = int(atom_text(root, "opensearch:totalResults"))
    if total_results < len(entries) or (total_results > 0 and not entries):
        raise ValueError("arXiv feed result count did not match its contents")

    cutoff = now.date() - timedelta(days=LOOKBACK_DAYS)
    newest = {}
    for entry in entries:
        paper_id = ARXIV_ID.fullmatch(atom_text(entry, "atom:id"))
        title = atom_text(entry, "atom:title")
        if paper_id is None or not title:
            raise ValueError("arXiv returned an error or an entry without valid metadata")
        identifier = paper_id.group("id")
        version = int(paper_id.group("version") or 0)
        published = parse_time(atom_text(entry, "atom:published"))
        if not cutoff <= published.date() <= now.date():
            continue
        if identifier not in newest or version > newest[identifier][0]:
            newest[identifier] = (version, published, title, entry)

    papers = []
    for identifier, (_, published, title, entry) in sorted(
        newest.items(), key=lambda item: item[1][1], reverse=True
    ):
        abstract = atom_text(entry, "atom:summary")
        methods, domains = classify(title, abstract)
        if not methods or not domains:
            continue

        authors = [atom_text(author, "atom:name") for author in entry.findall("atom:author", NAMESPACES)]
        categories = dict.fromkeys(
            category.get("term", "").strip() for category in entry.findall("atom:category", NAMESPACES)
        )
        paper = {
            "id": identifier,
            "title": title,
            "authors": ", ".join(filter(None, authors)),
            "abstract": abstract,
            "date": published.date().isoformat(),
            "categories": list(filter(None, categories)),
            "methods": methods,
            "domains": domains,
            "url": f"https://arxiv.org/abs/{identifier}",
            "pdfUrl": f"https://arxiv.org/pdf/{identifier}",
            "sources": ["arXiv"],
        }
        doi = crossref.normalize_doi(atom_text(entry, "arxiv:doi"))
        if doi:
            paper["doi"] = doi
        papers.append(paper)
    return papers


def arxiv_papers(now, feed_file):
    if feed_file:
        with feed_file.open("rb") as source:
            return parse_papers(source.read(MAX_FEED_BYTES + 1), now)

    searches = (
        (f"{search_group(METHOD_TERMS)} AND {search_group(DOMAIN_TERMS)}", MAX_RESULTS),
        (
            f"{search_group(COOPERATION_TERMS)} AND "
            + search_group(("control", "formation", "cooperation", "coordination", "platooning")),
            MAX_COOPERATION_RESULTS,
        ),
    )
    papers_by_id = {}
    errors = []
    for index, (query, limit) in enumerate(searches):
        if index:
            time.sleep(3.1)
        try:
            for paper in parse_papers(fetch_feed(query, limit), now):
                papers_by_id.setdefault(paper["id"], paper)
        except (URLError, OSError, ET.ParseError, ValueError) as error:
            errors.append(str(error))
    if errors:
        raise ValueError("arXiv search incomplete: " + "; ".join(errors))
    return list(papers_by_id.values())


def first_author_key(paper):
    name = crossref.normalize_title(paper["authors"].partition(",")[0])
    return name.split()[-1] if name else ""


def merge_papers(preprints, publications):
    papers = preprints.copy()
    by_doi = {}
    by_title = {}
    for preprint in preprints:
        if preprint.get("doi"):
            by_doi[preprint["doi"]] = preprint
        by_doi[f"10.48550/arxiv.{preprint['id'].lower()}"] = preprint
        by_title.setdefault(crossref.normalize_title(preprint["title"]), []).append(preprint)
    for publication in publications:
        related_dois = publication.pop("_relatedDois")
        preprint = next(
            (by_doi[doi] for doi in [publication["doi"], *related_dois] if doi in by_doi),
            None,
        )
        if preprint is None:
            exact_titles = by_title.get(crossref.normalize_title(publication["title"]), [])
            compatible_titles = [
                candidate for candidate in exact_titles
                if candidate.get("doi", publication["doi"]) == publication["doi"]
                and (
                    not publication["authors"] or not candidate["authors"]
                    or first_author_key(publication) == first_author_key(candidate)
                )
            ]
            if len(compatible_titles) == 1:
                preprint = compatible_titles[0]
        if preprint is None:
            if publication["methods"] and publication["domains"]:
                papers.append(publication)
            continue
        # Preserve the canonical arXiv ID and submission date, and retain the DOI as a separate link.
        if "Crossref" in preprint["sources"] and preprint["doi"] != publication["doi"]:
            if publication["methods"] and publication["domains"]:
                papers.append(publication)
            continue
        preprint.update({key: publication[key] for key in ("doi", "venue", "venueKind", "venueHighlight") if key in publication})
        preprint["publishedDate"] = publication["date"]
        preprint["publishedDatePrecision"] = publication["datePrecision"]
        preprint["sources"] = ["arXiv", "Crossref"]
        for key in ("methods", "domains"):
            preprint[key] = list(dict.fromkeys(preprint[key] + publication[key]))
    return sorted(papers, key=lambda paper: (paper["date"], paper["id"]), reverse=True)


def update_site(feed_file, output, crossref_file=None):
    now = datetime.now(timezone.utc)
    offline_arxiv_only = feed_file is not None and crossref_file is None
    errors = []
    try:
        preprints = arxiv_papers(now, feed_file)
    except (URLError, OSError, ET.ParseError, ValueError) as error:
        preprints = []
        errors.append(str(error))
        print(f"arXiv error: {error}", file=sys.stderr)
    publications = []
    if not offline_arxiv_only:
        try:
            publications = crossref.crossref_papers(crossref.crossref_records(now, crossref_file), now, classify)
        except (URLError, OSError, ValueError) as error:
            errors.append(str(error))
            print(f"Crossref error: {error}", file=sys.stderr)
    if errors:
        raise ValueError("one or more sources failed; existing data was preserved")
    papers = merge_papers(preprints, publications)
    if not papers and not offline_arxiv_only:
        raise ValueError("no matching papers returned; existing data was preserved")
    source_stats = {
        name: {
            "status": status,
            "count": sum(name in paper["sources"] for paper in papers),
            "url": url,
        }
        for name, status, url in (
            ("arXiv", "ok", SOURCE_URL),
            ("Crossref", "skipped" if offline_arxiv_only else "ok", crossref.SOURCE_URL),
        )
    }
    payload = {
        "sourceUrl": SOURCE_URL,
        "fetchedAt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sourceStats": source_stats,
        "papers": papers,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary_dir:
        temporary_file = Path(temporary_dir) / output.name
        temporary_file.write_text(f"window.PAPER_TRACKER_DATA = {encoded};\n", encoding="ascii")
        os.replace(temporary_file, output)
    print(f"Wrote {len(papers)} matching papers to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-file", type=Path, help="Read a local arXiv Atom fixture")
    parser.add_argument("--crossref-file", type=Path, help="Read a local Crossref work-list fixture")
    parser.add_argument("--output", type=Path, default=ROOT / "site" / "papers.js")
    args = parser.parse_args()
    try:
        update_site(args.feed_file, args.output, args.crossref_file)
    except (URLError, OSError, ET.ParseError, ValueError) as error:
        parser.exit(1, f"Paper refresh failed: {error}\n")


if __name__ == "__main__":
    main()
