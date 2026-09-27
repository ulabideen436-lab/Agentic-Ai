"""Stage every source in its original form, and index what was staged.

Staging copies each source byte for byte into data/raw/<source>/. Nothing is
parsed, cleaned or rewritten here, so when a parser has a bug later the
untouched originals are still on disk to re-run from.

Writes:
  data/raw/<source>/...            staged copies (gitignored)
  data/manifest.csv                one row per staged public/internal document
  data/private/manifest.csv        one row per private document (gitignored)

Private sources (real support conversations) are never copied: they are
dropped into data/private/<source>/ by hand and only indexed, into the
private manifest, because their file names alone may carry customer names.

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

MANIFEST_FIELDS = [
    "doc_id", "source", "title", "category", "language", "product_type",
    "last_updated", "visibility", "contains_personal_data", "raw_path", "sha256",
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

# Tables have no frontmatter, so their metadata lives here. "per_row" means the
# table's own visibility column decides, row by row; anything filtering on
# visibility == "public" leaves the whole table out, which is the safe default.
TABLES = {
    "prices_stock.csv": dict(doc_id="table-prices-stock", title="Retail prices and stock status",
                             category="structured", visibility="public"),
    "orders.csv": dict(doc_id="table-orders", title="Orders (synthetic)",
                       category="structured", visibility="per_row"),
}
TABLE_SOURCE = Source("structured", DATA / "structured", "*.csv")

CATALOGUE_SOURCE = "pos_catalogue"
CATALOGUE_ROW = dict(doc_id="pos-catalogue-export", title="POS catalogue export",
                     category="catalogue_export", visibility="internal")

# Private sources: indexed where they sit, never copied, never committed.
PRIVATE_SOURCES = ["support_conversations"]

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    missing = [k for k in MANIFEST_FIELDS if k not in {"source", "raw_path", "sha256"} and not meta.get(k)]
    if missing:
        raise SystemExit(f"{rel(staged)} is missing {missing}")
    if meta.get("raw_path") != rel(staged):
        raise SystemExit(f"{rel(staged)}: frontmatter raw_path is {meta.get('raw_path')!r}, "
                         f"but the document was staged at {rel(staged)!r}")
    row = {k: meta[k] for k in MANIFEST_FIELDS if k in meta}
    row.update(source=source.name, raw_path=rel(staged), sha256=sha256(staged))
    return row


def fixed_row(source_name: str, staged: Path, fields: dict[str, str]) -> dict[str, str]:
    return dict(fields, source=source_name, language="[en]", product_type="all",
                last_updated=modified(staged), contains_personal_data="false",
                raw_path=rel(staged), sha256=sha256(staged))


def stage_catalogue(catalogue: Path | None) -> list[dict[str, str]]:
    dest = RAW / CATALOGUE_SOURCE
    if catalogue:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(catalogue, dest / catalogue.name)
    # Kept between runs when no new export is given: it is the original, and
    # the product pages were generated from it.
    return [fixed_row(CATALOGUE_SOURCE, f, CATALOGUE_ROW) for f in sorted(dest.glob("*.json"))]


def private_rows() -> list[dict[str, str]]:
    rows = []
    for name in PRIVATE_SOURCES:
        folder = PRIVATE / name
        folder.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(sorted(p for p in folder.rglob("*") if p.is_file()), 1):
            rows.append(dict(doc_id=f"{name}-{i:04d}", source=name, title=f.name,
                             category="support_conversation", language="", product_type="all",
                             last_updated=modified(f), visibility="internal",
                             contains_personal_data="true", raw_path=rel(f), sha256=sha256(f)))
    return rows


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

    ids = [r["doc_id"] for r in rows]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SystemExit(f"Duplicate doc_id: {duplicates}")
    leaking = [r["raw_path"] for r in rows if r["contains_personal_data"] != "false"]
    if leaking:
        raise SystemExit(f"Personal data in a committed source; move it to data/private/: {leaking}")

    write(DATA / "manifest.csv", rows)
    private = private_rows()
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
