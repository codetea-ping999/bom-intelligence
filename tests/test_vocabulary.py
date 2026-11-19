from __future__ import annotations

import json
from pathlib import Path

import pytest

from bom_intelligence.vocabulary import FieldCategory, Vocabulary, normalize_label


def test_normalize_label() -> None:
    assert normalize_label("Part No.") == "partno"
    assert normalize_label("単価（円）") == "単価"
    assert normalize_label("ＰＡＲＴ　ＮＯ") == "partno"


@pytest.mark.parametrize(
    ("text", "category", "subtype"),
    [
        ("品番", FieldCategory.PART_NUMBER, None),
        ("Part Number", FieldCategory.PART_NUMBER, None),
        ("量産単価(円)", FieldCategory.COST, "production"),
        ("SOP", FieldCategory.SCHEDULE, "sop"),
        ("納期", FieldCategory.SCHEDULE, "delivery"),
    ],
)
def test_default_header_matches(text: str, category: FieldCategory, subtype: str | None) -> None:
    match = Vocabulary.load().match_header(text)
    assert match is not None
    assert match.category is category
    assert match.subtype == subtype


def test_keywords_skip_short_ascii_aliases() -> None:
    vocab = Vocabulary.load()
    assert vocab.find_keywords("open the panel") == []
    assert [m.category for m in vocab.find_keywords("Unit Price per piece")] == [FieldCategory.COST]


def test_custom_alias_file(tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({"part_number": ["Teil-Nr"], "cost": [["Preis", "unknown"]]}))
    vocab = Vocabulary.load(path)
    assert vocab.match_header("Teil Nr") is not None
    assert vocab.match_header("品番") is None


def test_conflicting_alias_rejected() -> None:
    with pytest.raises(ValueError, match="maps to both"):
        Vocabulary.from_mapping({"part_number": ["X1"], "cost": ["x1"]})
