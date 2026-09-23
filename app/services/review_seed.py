"""Compatibility export for the canonical bilingual catalog seed."""
import json
from pathlib import Path

LESSON = next(row["content"] for row in json.loads((Path(__file__).parents[1] / "data/review-catalog.json").read_text(encoding="utf-8"))["lessons"] if row["id"] == "newton-third-law")
