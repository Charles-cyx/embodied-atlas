"""Fetch publication metadata and identify tracked venues from Crossref deposits."""

import json
import os
import re
import time
import unicodedata
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


SOURCE_URL = "https://www.crossref.org/"
API_URL = "https://api.crossref.org/works"
LOOKBACK_DAYS = 365
ROWS_PER_QUERY = 60
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
SEARCH_QUERIES = (
    "vision language action model robotics",
    "world action model robotics",
    "world model autonomous driving",
    "world model robot control",
    "unmanned ground vehicles formation control",
    "vehicle platoon cooperative control",
    "multi robot formation cooperative control",
)
WORK_TYPES = ("journal-article", "proceedings-article", "book-chapter")

# The whitelist applies to publication identity only. It does not assign paper awards.
PRIORITY_JOURNALS = (
    ("T-RO", "IEEE Transactions on Robotics", ("1552-3098", "1941-0468")),
    ("RA-L", "IEEE Robotics and Automation Letters", ("2377-3766",)),
    ("IJRR", "The International Journal of Robotics Research", ("0278-3649", "1741-3176")),
    ("Science Robotics", "Science Robotics", ("2470-9476",)),
    ("T-ITS", "IEEE Transactions on Intelligent Transportation Systems", ("1524-9050", "1558-0016")),
    ("T-IV", "IEEE Transactions on Intelligent Vehicles", ("2379-8858", "2379-8904")),
    ("TAC", "IEEE Transactions on Automatic Control", ("0018-9286", "1558-2523")),
    ("Automatica", "Automatica", ("0005-1098", "1873-2836")),
    ("TPAMI", "IEEE Transactions on Pattern Analysis and Machine Intelligence", ("0162-8828", "1939-3539")),
    ("TCST", "IEEE Transactions on Control Systems Technology", ("1063-6536", "1558-0865")),
)
PRIORITY_CONFERENCES = (
    ("ICRA", r"(?:ieee )?international conference on robotics and automation(?: icra)?"),
    ("IROS", r"(?:ieee rsj )?international conference on intelligent robots and systems(?: iros)?"),
    ("RSS", r"robotics science and systems(?: rss)?(?: [ivxlc]+)?"),
    ("CoRL", r"conference on robot learning(?: corl)?"),
    ("CVPR", r"(?:ieee cvf )?conference on computer vision and pattern recognition(?: cvpr)?"),
    ("ICCV", r"(?:ieee cvf )?international conference on computer vision(?: iccv)?"),
    ("ECCV", r"(?:european conference on computer vision(?: eccv)?|computer vision eccv)"),
    ("NeurIPS", r"(?:advances in )?neural information processing systems(?: neurips| nips)?(?: \d{1,2})?"),
    ("ICML", r"international conference on machine learning(?: icml)?"),
    ("ICLR", r"international conference on learning representations(?: iclr)?"),
    ("CDC", r"(?:ieee )?conference on decision and control(?: cdc)?"),
    ("ACC", r"american control conference(?: acc)?"),
)
CONFERENCE_PREFIX = r"(?:proceedings of (?:the )?)?(?:\d{4} )?(?:\d+(?:st|nd|rd|th) )?"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s<>]+")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []

    def handle_data(self, data):
        self.chunks.append(data)


def plain_text(value):
    if not isinstance(value, str):
        return ""
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return " ".join(" ".join(parser.chunks).split())


def first_text(record, key):
    values = record.get(key)
    return plain_text(values[0]) if isinstance(values, list) and values else ""


def normalize_title(value):
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", normalized))


def normalize_doi(value):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.IGNORECASE).lower()
    return value if DOI_PATTERN.fullmatch(value) else ""


def venue_info(record, work_type):
    container = first_text(record, "container-title")
    if work_type == "journal-article":
        issns = set(record.get("ISSN") or [])
        title = normalize_title(container).removeprefix("the ")
        for short, full, recognized_issns in PRIORITY_JOURNALS:
            if issns.intersection(recognized_issns) or title == normalize_title(full).removeprefix("the "):
                return {"venue": short, "venueKind": "journal", "venueHighlight": True}
        return {"venue": container, "venueKind": "journal", "venueHighlight": False} if container else {}

    event = record.get("event") or {}
    event_name = plain_text(event.get("name"))
    for candidate in (event_name, container):
        normalized = normalize_title(candidate)
        for short, pattern in PRIORITY_CONFERENCES:
            if re.fullmatch(rf"{CONFERENCE_PREFIX}(?:{pattern})(?: \d{{4}})?", normalized):
                return {"venue": short, "venueKind": "conference", "venueHighlight": True}
    if work_type == "proceedings-article" and (event_name or container):
        return {"venue": event_name or container, "venueKind": "conference", "venueHighlight": False}
    return {}


def publication_date(record):
    candidates = []
    for key in ("published-online", "published-print", "published", "issued"):
        parts = (record.get(key) or {}).get("date-parts") or []
        if not parts:
            continue
        values = parts[0]
        if not values or any(type(value) is not int for value in values):
            continue
        try:
            published = date(*(values + [1] * (3 - len(values))))
        except (TypeError, ValueError, OverflowError):
            continue
        candidates.append((published, len(values)))
    if candidates:
        precision = max(precision for _, precision in candidates)
        published = min(value for value, detail in candidates if detail == precision)
        return published, ("year", "month", "day")[precision - 1]
    return None, None


def records_from_response(response):
    try:
        if response["status"] != "ok" or response["message-type"] != "work-list":
            raise ValueError("Crossref returned an unexpected response type")
        items = response["message"]["items"]
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("Crossref returned malformed publication records")
        return items
    except (KeyError, TypeError) as error:
        raise ValueError("Crossref returned a malformed response") from error


def crossref_records(now, fixture=None):
    if fixture:
        with Path(fixture).open("rb") as source:
            return records_from_response(json.load(source))

    cutoff = now.date() - timedelta(days=LOOKBACK_DAYS)
    types = ",".join(f"type:{work_type}" for work_type in WORK_TYPES)
    contact = os.environ.get("PAPER_TRACKER_CROSSREF_MAILTO")
    records = []
    failures = []
    next_request = 0.0
    for query in SEARCH_QUERIES:
        time.sleep(max(0, next_request - time.monotonic()))
        next_request = time.monotonic() + 1.1
        params = {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{cutoff},until-pub-date:{now.date()},{types}",
            "rows": ROWS_PER_QUERY,
            "select": (
                "DOI,title,abstract,author,container-title,event,ISSN,type,"
                "published,published-online,published-print,issued,relation"
            ),
        }
        if contact:
            params["mailto"] = contact
        request = Request(
            f"{API_URL}?{urlencode(params)}",
            headers={"Accept": "application/json", "User-Agent": "PaperTracker/2.0"},
        )
        try:
            with urlopen(request, timeout=18) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
            records.extend(records_from_response(json.loads(payload)))
        except HTTPError as error:
            failures.append(f"{query}: HTTP {error.code}")
            if error.code in (403, 429):
                break
        except (URLError, OSError, ValueError) as error:
            failures.append(f"{query}: {error}")
    if failures:
        raise ValueError("Crossref search incomplete: " + "; ".join(failures))
    return records


def related_preprint_dois(record):
    relation = record.get("relation") or {}
    if not isinstance(relation, dict):
        return []
    return [
        doi for item in relation.get("has-preprint", [])
        if isinstance(item, dict) and item.get("id-type") == "doi"
        if (doi := normalize_doi(item.get("id")))
    ]


def crossref_papers(records, now, classify):
    cutoff = now.date() - timedelta(days=LOOKBACK_DAYS)
    papers = []
    seen = set()
    for record in records:
        doi = normalize_doi(record.get("DOI"))
        work_type = record.get("type")
        title = first_text(record, "title")
        if not doi or doi in seen or not title or work_type not in WORK_TYPES:
            continue
        venue = venue_info(record, work_type)
        if work_type == "book-chapter" and venue.get("venueKind") != "conference":
            continue
        published, precision = publication_date(record)
        if published is None or not cutoff <= published <= now.date():
            continue
        methods, domains = classify(title, plain_text(record.get("abstract")))
        # Keep nonmatching records for DOI/title enrichment of matching preprints.
        authors = [
            " ".join(filter(None, (plain_text(author.get("given")), plain_text(author.get("family")))))
            or plain_text(author.get("name"))
            for author in record.get("author") or [] if isinstance(author, dict)
        ]
        papers.append({
            "id": f"doi:{doi}",
            "title": title,
            "authors": ", ".join(filter(None, authors)),
            # Crossref warns that some publisher-deposited abstracts are copyrighted.
            "abstract": "",
            "date": published.isoformat(),
            "datePrecision": precision,
            "categories": [],
            "methods": methods,
            "domains": domains,
            "url": f"https://doi.org/{quote(doi, safe='/')}",
            "pdfUrl": "",
            "doi": doi,
            "sources": ["Crossref"],
            "_relatedDois": related_preprint_dois(record),
            **venue,
        })
        seen.add(doi)
    return papers
