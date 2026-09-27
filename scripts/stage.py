"""Stage every source in its original form, and index what was staged.

Staging copies each source byte for byte into data/raw/<source>/. Nothing is
parsed, cleaned or rewritten here, so when a parser has a bug later the
untouched originals are still on disk to re-run from.

Writes:
  data/raw/<source>/...            staged copies (gitignored)
  data/manifest.csv                one row per staged public/internal document
  data/private/manifest.csv        one row per private document (gitignored)
  data/private/conversation_ids.csv  the stable ID given to each chat (gitignored)

Private sources (support conversations) are never copied: they are dropped into
data/private/<source>/ by hand and only indexed, into the private manifest,
because their file names alone carry customer names.

Manifest columns follow Appendix C. Document IDs are stable: written once into
each document's frontmatter, never derived from file names or file order, so
renaming a file never breaks an eval label that cites it.

Usage:
  python scripts/stage.py
  python scripts/stage.py --catalogue <path to the POS products-export.json>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PRIVATE = DATA / "private"

# Appendix C, in its order.
MANIFEST_FIELDS = [
    "doc_id", "source", "title", "language", "doc_type",
    "last_updated", "contains_personal_data", "raw_path",
]
LANGUAGES = {"en", "ur", "roman_ur", "mixed"}
# <type>-<name>-<nnn>, e.g. policy-returns-001, product-zy0000000005-001, chat-001.
DOC_ID = re.compile(r"^[a-z]+(-[a-z0-9]+)*-\d{3}$")

# Frontmatter must carry these even though the manifest does not: the permission
# filter needs visibility and the metadata filter needs product_type.
FRONTMATTER_REQUIRED = [
    "doc_id", "title", "doc_type", "language", "last_updated",
    "contains_personal_data", "raw_path", "visibility", "product_type",
]


@dataclass(frozen=True)
class Source:
    name: str
    origin: Path
    pattern: str


# Documents written in data/corpus/, which carry their own metadata as frontmatter.
DOCUMENT_SOURCES = [
    Source("policies", DATA / "corpus" / "policies", "*.md"),
    Source("shipping", DATA / "corpus" / "shipping", "*.md"),
    Source("size_guides", DATA / "corpus" / "size_guides", "*.md"),
    Source("fabric_guides", DATA / "corpus" / "fabric_guides", "*.md"),
    Source("care", DATA / "corpus" / "care", "*.md"),
    Source("products", DATA / "corpus" / "products", "*.md"),
    Source("support_qa", DATA / "corpus" / "support_qa", "*.md"),
]

# Tables and the catalogue have no frontmatter, so their metadata lives here.
TABLES = {
    "prices_stock.csv": dict(doc_id="table-prices-stock-001", title="Retail prices and stock status",
                             doc_type="structured", language="en"),
    "orders.csv": dict(doc_id="table-orders-001", title="Orders (synthetic)",
                       doc_type="structured", language="en"),
}
TABLE_SOURCE = Source("structured", DATA / "structured", "*.csv")

CATALOGUE_SOURCE = "pos_catalogue"
CATALOGUE_ROW = dict(doc_id="catalogue-pos-export-001", title="POS catalogue export",
                     doc_type="catalogue_export", language="en")

# Private sources: indexed where they sit, never copied, never committed.
CONVERSATIONS = PRIVATE / "support_conversations"
CONVERSATION_IDS = PRIVATE / "conversation_ids.csv"

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def modified(path: Path) -> str:
    return date.fromtimestamp(path.stat().st_mtime).isoformat()


def frontmatter(path: Path) -> dict[str, str]:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"No frontmatter in {rel(path)}")
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta


def restage(source: Source) -> list[Path]:
    """Replace data/raw/<source>/ with a fresh byte-for-byte copy of the origin."""
    dest = RAW / source.name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    staged = []
    for original in sorted(source.origin.glob(source.pattern)):
        copy = dest / original.name
        shutil.copy2(original, copy)
        staged.append(copy)
    return staged


def document_row(source: Source, staged: Path) -> dict[str, str]:
    meta = frontmatter(staged)
    missing = [k for k in FRONTMATTER_REQUIRED if not meta.get(k)]
    if missing:
        raise SystemExit(f"{rel(staged)} is missing {missing}")
    if meta["raw_path"] != rel(staged):
        raise SystemExit(f"{rel(staged)}: frontmatter raw_path is {meta['raw_path']!r}, "
                         f"but the document was staged at {rel(staged)!r}")
    row = {k: meta[k] for k in MANIFEST_FIELDS if k in meta}
    row.update(source=source.name, raw_path=rel(staged))
    return row


def fixed_row(source_name: str, staged: Path, fields: dict[str, str]) -> dict[str, str]:
    return dict(fields, source=source_name, last_updated=modified(staged),
                contains_personal_data="false", raw_path=rel(staged))


def stage_catalogue(catalogue: Path | None) -> list[dict[str, str]]:
    dest = RAW / CATALOGUE_SOURCE
    if catalogue:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(catalogue, dest / catalogue.name)
    # Kept between runs when no new export is given: it is the original, and
    # the product pages were generated from it.
    return [fixed_row(CATALOGUE_SOURCE, f, CATALOGUE_ROW) for f in sorted(dest.glob("*.json"))]


# --- private: support conversations -------------------------------------------

URDU_SCRIPT = re.compile(r"[؀-ۿ]")
WORD = re.compile(r"[a-z']+")
ROMAN_UR = {"hai", "hain", "ka", "ki", "ke", "kya", "kia", "nahi", "nai", "aap", "ap", "bhai", "hun",
            "mein", "kar", "kr", "dein", "se", "ko", "tak", "tk", "abhi", "abi", "wala", "wali",
            "chahiye", "kitne", "kitna", "theek", "acha", "bhej", "sath", "ye", "wo", "phir", "baji",
            "ji", "hum", "dia", "gaya", "gya", "raha", "rahi", "lun", "doge", "sakte", "hota", "ho"}
ENGLISH = {"the", "is", "are", "i", "you", "to", "and", "please", "thank", "my", "it", "for", "can",
           "what", "how", "why", "want", "would", "like", "still", "on", "of", "this", "was", "we"}
MESSAGE = re.compile(r"^\d{2}/\d{2}/\d{4}, [^-]+ - [^:]+: (.*)$")
# Lines WhatsApp writes itself; they say nothing about the customer's language.
SYSTEM_TEXT = {"This message was deleted", "You deleted this message", "(voice note)"}


def conversation_language(path: Path) -> str:
    """Rough per-message vote. Good enough to sort chats for eval writing; not a classifier."""
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = MESSAGE.match(line)
        if not match or match.group(1).startswith("<") or match.group(1).strip() in SYSTEM_TEXT:
            continue
        text = match.group(1)
        if URDU_SCRIPT.search(text):
            seen.add("ur")
            continue
        words = WORD.findall(text.lower())
        roman, english = sum(w in ROMAN_UR for w in words), sum(w in ENGLISH for w in words)
        if roman > english:
            seen.add("roman_ur")
        elif english > roman:
            seen.add("en")
    return seen.pop() if len(seen) == 1 else "mixed"


def conversation_key(path: Path) -> str:
    """The first two lines of a WhatsApp export: the chat's start. They survive both a
    file rename and a fresh export of the same chat, so the ID keyed on them does too."""
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:2])
    return hashlib.sha256(head.encode("utf-8")).hexdigest()[:16]


def conversation_rows() -> list[dict[str, str]]:
    CONVERSATIONS.mkdir(parents=True, exist_ok=True)
    registry = {}
    if CONVERSATION_IDS.exists():
        registry = {r["key"]: r["doc_id"] for r in csv.DictReader(CONVERSATION_IDS.open(encoding="utf-8"))}
    next_number = 1 + max((int(i.rsplit("-", 1)[1]) for i in registry.values()), default=0)

    # A path Windows cannot open (over 260 characters) reports is_file() False
    # rather than raising, which would drop the chat from the manifest silently.
    unreadable = [p for p in CONVERSATIONS.rglob("*") if not p.is_dir() and not p.is_file()]
    if unreadable:
        raise SystemExit(f"Cannot read {[rel(p) for p in unreadable]}; shorten the path or file name")

    rows, seen = [], {}
    for f in sorted(p for p in CONVERSATIONS.rglob("*") if p.is_file()):
        key = conversation_key(f)
        if key in seen:
            raise SystemExit(f"{rel(f)} and {rel(seen[key])} are the same chat; keep the newer export only")
        seen[key] = f
        if key not in registry:
            # Numbers are never reused, even when a chat is deleted.
            registry[key] = f"chat-{next_number:03d}"
            next_number += 1
        rows.append(dict(doc_id=registry[key], source=CONVERSATIONS.name, title=f.stem,
                         language=conversation_language(f), doc_type="support_conversation",
                         last_updated=modified(f), contains_personal_data="true", raw_path=rel(f)))

    with CONVERSATION_IDS.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["key", "doc_id"])
        writer.writerows(sorted(registry.items(), key=lambda kv: kv[1]))
    return sorted(rows, key=lambda r: r["doc_id"])


# --- checks and output ----------------------------------------------------------

def validate(rows: list[dict[str, str]]) -> None:
    ids = [r["doc_id"] for r in rows]
    problems = [f"duplicate doc_id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    problems += [f"{r['doc_id']}: doc_id is not <type>-<name>-<nnn>" for r in rows if not DOC_ID.match(r["doc_id"])]
    problems += [f"{r['doc_id']}: language {r['language']!r} is not one of {sorted(LANGUAGES)}"
                 for r in rows if r["language"] not in LANGUAGES]
    problems += [f"{r['doc_id']}: empty {k}" for r in rows for k in MANIFEST_FIELDS if not r.get(k)]
    if problems:
        raise SystemExit("Manifest problems:\n  " + "\n  ".join(problems))


def write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check_ignored() -> None:
    """Refuse to finish if git would pick up anything staged or private."""
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "data/raw", "data/private"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    if out.strip():
        raise SystemExit("data/raw or data/private is visible to git. Fix .gitignore before committing:\n" + out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalogue", type=Path, help="POS products-export.json to stage as pos_catalogue")
    args = parser.parse_args()

    rows = []
    for source in DOCUMENT_SOURCES:
        rows += [document_row(source, f) for f in restage(source)]
    rows += [fixed_row(TABLE_SOURCE.name, f, TABLES[f.name]) for f in restage(TABLE_SOURCE)]
    rows += stage_catalogue(args.catalogue)
    private = conversation_rows()

    validate(rows + private)
    leaking = [r["raw_path"] for r in rows if r["contains_personal_data"] != "false"]
    if leaking:
        raise SystemExit(f"Personal data in a committed source; move it to data/private/: {leaking}")

    write(DATA / "manifest.csv", rows)
    write(PRIVATE / "manifest.csv", private)
    check_ignored()

    by_source = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    for name, count in by_source.items():
        print(f"{count:4d}  {name}")
    print(f"{len(rows):4d}  staged -> data/manifest.csv")
    print(f"{len(private):4d}  private -> data/private/manifest.csv")
    if CATALOGUE_SOURCE not in by_source:
        print("note: pos_catalogue not staged; run again with --catalogue <products-export.json>")


if __name__ == "__main__":
    main()
