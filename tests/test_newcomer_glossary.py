from pathlib import Path
import re


def test_newcomer_glossary_local_links_resolve():
    repository_root = Path(__file__).resolve().parents[1]
    glossary = repository_root / "docs" / "NEWCOMER_GLOSSARY.md"
    markdown = glossary.read_text(encoding="utf-8")

    local_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", markdown)
    assert local_links, "glossary should contain local documentation links"

    missing = []
    for target in local_links:
        if "://" in target or target.startswith("#"):
            continue
        target_path = (glossary.parent / target).resolve()
        if not target_path.exists():
            missing.append(target)

    assert not missing, f"glossary links point to missing files: {missing}"
