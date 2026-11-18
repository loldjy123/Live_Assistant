"""Saved book evidence, inventory corrections and deterministic price totals."""

import base64
import copy
import hashlib
import html
import io
import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

from PIL import Image
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, field_validator

SCHEMA_PATH = Path(__file__).with_name("output_schema.json")


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class BookObservation(BaseModel):
    kind: Literal["book"] = "book"
    existing_id: str = ""
    possible_duplicate_of: str = ""
    title: str = ""
    author: str = ""
    publisher: str = ""
    edition: str = ""
    description: str = ""
    shelf: str = ""
    position: int = Field(default=0, ge=0)
    bbox: list[int] = Field(min_length=4, max_length=4)
    confidence: float = Field(ge=0, le=1)
    needs_appraisal: bool = False


class BookIdentification(BaseModel):
    observations: list[BookObservation] = Field(default_factory=list, max_length=80)
    capture_issues: list[str] = Field(default_factory=list)

    @field_validator("observations", mode="before")
    @classmethod
    def keep_books(cls, observations):
        # Discard a stray non-book detection without losing valid books from
        # the same frame. The public model itself only accepts kind="book".
        if isinstance(observations, list):
            return [
                observation
                for observation in observations
                if not isinstance(observation, dict) or observation.get("kind", "book") == "book"
            ]
        return observations


class BookPriceCandidate(BaseModel):
    valuation: str = Field(pattern="^(replacement|used)$")
    amount: float = Field(ge=0)
    currency: str
    country: str
    source: str
    url: str
    condition: str
    quote: str
    match_notes: str = ""


class BookPriceExtraction(BaseModel):
    prices: list[BookPriceCandidate] = Field(default_factory=list)


def valid_box(box):
    top, left, bottom, right = box
    return 0 <= top < bottom <= 1000 and 0 <= left < right <= 1000


def sum_money(values):
    total = sum((Decimal(str(value)) for value in values), Decimal("0"))
    return float(total.quantize(Decimal(".01")))


def counted(book):
    return not any(book.get(flag) for flag in ["excluded", "duplicate_of", "possible_duplicate_of"])


def identified(book):
    return bool(book.get("title", "").strip()) and book.get("status") != "unidentified"


def eligible_for_pricing(book):
    return counted(book) and identified(book) and not book.get("needs_appraisal")


def needs_appraisal(book):
    description = (book["edition"] + " " + book["description"]).lower()
    return book["needs_appraisal"] or any(
        word in description for word in ["signed", "first edition", "rare", "antiquarian"]
    )


class ClaimStore:
    def __init__(self, root, device="browser", country="", currency=""):
        self.id = uuid.uuid4().hex
        self.directory = Path(root) / self.id
        (self.directory / "frames").mkdir(parents=True)
        (self.directory / "research").mkdir()
        self.started = time.monotonic()
        self.data = {
            "sweep": {
                "id": self.id,
                "captured_at": now(),
                "device": device,
                "duration_s": 0,
                "country": country,
                "currency": currency,
            },
            "books": [],
            "frames": [],
            "review_queue": [],
            "corrections": [],
            "stage_metrics": [],
            "status": "capturing",
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": None,
                "note": "Exact cost is unknown; consult provider billing.",
            },
        }
        self.save()

    def event(self, name, details):
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": now(), "event": name, "details": details}) + "\n")

    def review(self, ref, reason):
        entry = {"ref_id": ref, "reason": reason}
        if entry not in self.data["review_queue"]:
            self.data["review_queue"].append(entry)

    def books(self):
        return self.data["books"]

    def get_book(self, book_id):
        return next((book for book in self.books() if book["id"] == book_id), None)

    def save(self):
        self.data["totals"] = self.totals()
        write_json(self.directory / "inventory.json", self.data)

    def save_frame(self, encoded):
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 8_000_000:
            raise ValueError("Frame exceeds 8 MB")

        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "JPEG" or image.width * image.height > 20_000_000:
                raise ValueError("Expected a JPEG image of at most 20 megapixels")
            image.verify()

        frame_id = f'frame_{len(self.data["frames"]) + 1:05d}'
        ref = f"frames/{frame_id}.jpg"
        (self.directory / ref).write_bytes(raw)
        frame = {
            "id": frame_id,
            "ref": ref,
            "captured_at": now(),
            "status": "queued",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        self.data["frames"].append(frame)
        self.save()
        return frame

    def apply_observations(self, result, frame):
        for problem in result.capture_issues:
            self.review(frame["id"], problem)

        changed = []
        for observation in result.observations:
            if not valid_box(observation.bbox):
                self.review(frame["id"], "Invalid book bounding box rejected")
                continue

            book = observation.model_dump()
            existing = self.get_book(book.pop("existing_id"))
            evidence = {
                "frame_ref": frame["ref"],
                "bbox": book["bbox"],
                "observed_at": now(),
                "confidence": book["confidence"],
            }

            if existing:
                existing["evidence"].append(evidence)
                protected = {
                    entry["field"]
                    for entry in self.data["corrections"]
                    if entry["book_id"] == existing["id"]
                }
                improved = False
                for field in ["title", "author", "publisher", "edition", "description"]:
                    if not existing.get(field) and book[field] and field not in protected:
                        existing[field] = book[field]
                        improved = True
                if book["needs_appraisal"] and not existing["needs_appraisal"]:
                    existing["needs_appraisal"] = True
                    improved = True
                if improved:
                    existing["needs_appraisal"] = needs_appraisal(existing)
                    existing["revision"] += 1
                    existing.update(replacement_cost=None, used_value=None)
                    existing["id_confidence"] = max(existing["id_confidence"], book["confidence"])
                    self.update_status(existing)
                    changed.append(existing)
                continue

            book.update(
                id=uuid.uuid4().hex[:12],
                frame_ref=frame["ref"],
                evidence=[evidence],
                id_confidence=book.pop("confidence"),
                revision=0,
                isbn="",
                replacement_cost=None,
                used_value=None,
                excluded=False,
                duplicate_of="",
            )
            book["needs_appraisal"] = needs_appraisal(book)
            self.update_status(book)
            if book["needs_appraisal"]:
                self.review(
                    book["id"], "Human appraisal required; excluded from automatic valuation"
                )
            if book["possible_duplicate_of"]:
                self.review(
                    book["id"], "Possible duplicate; excluded from count and totals pending review"
                )
            if book["id_confidence"] < 0.85 or not book["title"]:
                self.review(book["id"], "Book identification needs verification")
            self.data["books"].append(book)
            changed.append(book)

        frame["status"] = "identified"
        self.save()
        return changed

    def update_status(self, book):
        if book["needs_appraisal"]:
            book["status"] = "needs_appraisal"
            book["stage"] = "needs_review"
        else:
            book["status"] = "identified" if book["title"].strip() else "unidentified"
            book["stage"] = "identified"

    def set_locale(self, country, currency):
        country = country.strip()
        currency = currency.strip().upper()
        if not country or len(country) > 100 or len(currency) != 3 or not currency.isalpha():
            raise ValueError("Provide a country and a three-letter currency code")

        sweep = self.data["sweep"]
        if (sweep["country"], sweep["currency"]) != (country, currency):
            for book in self.books():
                book.update(replacement_cost=None, used_value=None, revision=book["revision"] + 1)
                self.update_status(book)
            sweep.update(country=country, currency=currency)
        self.event("locale", {"country": country, "currency": currency})
        self.save()

    def correct(self, book_id, field, value):
        allowed = {
            "title",
            "author",
            "publisher",
            "edition",
            "description",
            "shelf",
            "excluded",
            "duplicate_of",
        }
        book = self.get_book(book_id)
        if not book or field not in allowed:
            raise ValueError("Unknown book or unsupported correction field")
        if field == "excluded" and not isinstance(value, bool):
            raise ValueError("Exclusion requires true or false")
        if field != "excluded" and not isinstance(value, str):
            raise ValueError("This correction requires text")
        if field == "duplicate_of" and value and (value == book_id or not self.get_book(value)):
            raise ValueError("Duplicate target must be another existing book")

        correction = {
            "book_id": book_id,
            "field": field,
            "value": value,
            "source": "user",
            "at": now(),
        }
        self.data["corrections"].append(correction)
        book[field] = value
        book["revision"] += 1
        book.update(replacement_cost=None, used_value=None)
        if field == "duplicate_of":
            book["possible_duplicate_of"] = ""
        book["needs_appraisal"] = needs_appraisal(book)
        self.update_status(book)
        self.review(book_id, "User correction recorded; verify against evidence")
        self.event("correction", correction)
        self.save()
        return book

    def totals(self):
        books = self.data["books"]
        counted_books = [book for book in books if counted(book)]
        identified_count = sum(identified(book) for book in counted_books)

        def prices(field):
            return [
                book[field]["amount"]
                for book in books
                if eligible_for_pricing(book) and book.get(field)
            ]

        return {
            "book_count": len(counted_books),
            "books_identified": identified_count,
            "books_unidentified": len(counted_books) - identified_count,
            "books_priced": sum(
                bool(book.get("replacement_cost") and book.get("used_value"))
                for book in books
                if eligible_for_pricing(book)
            ),
            "books_replacement_cost": sum_money(prices("replacement_cost")),
            "books_used_value": sum_money(prices("used_value")),
            "excluded_from_totals": sum(
                not eligible_for_pricing(book) or not book.get("replacement_cost") for book in books
            ),
        }

    def finalize_packet(self):
        for book in self.books():
            if not book.get("replacement_cost"):
                self.review(
                    book["id"], "No supported replacement price; excluded from replacement total"
                )
            if not book.get("used_value"):
                self.review(book["id"], "No supported used price; excluded from used total")
        self.data["totals"] = self.totals()
        self.data["assumptions"] = [
            "Book counts and cross-frame physical tracking are provisional.",
            "Prices are sourced listings, not appraisals or confirmed sales.",
            "Unknown prices are null and excluded from the corresponding total.",
            "Non-books and all measurement features are outside scope.",
        ]
        return self.data


def build_output_packet(inventory):
    """Export only the screenshot's book fields; retain diagnostics internally."""
    book_fields = [
        "id",
        "shelf",
        "position",
        "frame_ref",
        "status",
        "title",
        "author",
        "edition",
        "isbn",
        "id_confidence",
    ]
    common_price_fields = ["amount", "source", "url", "retrieved_at"]

    books = []
    for book in inventory["books"]:
        if book.get("kind") != "book" or not counted(book) or not identified(book):
            continue
        entry = {field: book[field] for field in book_fields}
        # Measurement features remain disabled. Unknown is not a zero measurement.
        entry["spine_height_cm"] = None
        entry["spine_thickness_cm"] = None

        replacement = book["replacement_cost"]
        entry["replacement_cost"] = (
            {**{key: replacement[key] for key in common_price_fields}, "converted": False}
            if replacement
            else None
        )
        used = book["used_value"]
        entry["used_value"] = (
            {
                **{key: used[key] for key in common_price_fields},
                "condition_assumed": used["condition_assumed"],
            }
            if used
            else None
        )
        books.append(entry)

    totals = inventory["totals"]
    packet = copy.deepcopy(
        {
            "sweep": inventory["sweep"],
            "books": books,
            "totals": {
                "book_count": totals["book_count"],
                "books_identified": totals["books_identified"],
                "books_unidentified": totals["books_unidentified"],
                "shelf_run_m": None,
                "books_replacement_cost": totals["books_replacement_cost"],
                "books_used_value": totals["books_used_value"],
                "excluded_from_totals": totals["excluded_from_totals"],
            },
        }
    )

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(packet)
    return packet


def render_report(packet, narrative=""):
    """Render the same book-only output as JSON, with escaped text and sources."""

    def escape(value):
        return html.escape(str(value if value is not None else "Unknown"))

    def price(value):
        if not value:
            return "Unknown / excluded"
        url = value["url"]
        source = (
            f'<a href="{escape(url)}">{escape(value["source"])}</a>'
            if url.startswith("https://")
            else escape(url)
        )
        return (
            f'{escape(value["amount"])} {escape(packet["sweep"]["currency"])} — {source}<br>'
            f'{escape(value["retrieved_at"])}'
            + (f'; {escape(value["condition_assumed"])}' if value.get("condition_assumed") else "")
        )

    rows = []
    for book in packet["books"]:
        if not identified(book) or not counted(book):
            continue
        title = book["title"]
        evidence = f'<a href="{escape(book["frame_ref"])}">Frame</a>'
        cells = [
            escape(title),
            escape(book["author"]),
            escape(book["status"]),
            price(book["replacement_cost"]),
            price(book["used_value"]),
            evidence,
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")

    totals = packet["totals"]
    currency = escape(packet["sweep"]["currency"])
    omitted_count = totals.get("books_unidentified", 0)
    omitted_note = (
        f"<p>{omitted_count} detected books had unreadable titles and are omitted from this list.</p>"
        if omitted_count
        else ""
    )
    inventory_rows = "".join(rows)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Book inventory report</title>
<style>body{{font:16px system-ui;margin:2rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:8px;text-align:left}}a{{overflow-wrap:anywhere}}</style>
</head><body><h1>Book inventory report — provisional</h1>
<p>{escape(narrative)}</p>
<p>Books identified: {totals['books_identified']} of {totals['book_count']} detected · Replacement total: {totals['books_replacement_cost']} {currency} · Used total: {totals['books_used_value']} {currency}</p>
{omitted_note}
<p>Unknown, excluded, duplicate and appraisal-only prices do not contribute to monetary totals. Counts remain provisional.</p>
<table><tr><th>Book</th><th>Author</th><th>Status</th><th>Replacement</th><th>Used</th><th>Evidence</th></tr>{inventory_rows}</table>
</body></html>"""
