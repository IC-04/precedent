from pathlib import Path

from precedent.worker.compact import (
    compact_snapshot,
    inline_snapshot,
    one_line,
    page_of,
    strip_code,
)

FIX = Path(__file__).parent / "fixtures" / "snapshots"


def test_dropdowns_become_one_line_and_keep_every_option():
    raw = (FIX / "bill_new.txt").read_text()
    small = compact_snapshot(raw)
    assert len(small) < len(raw) * 0.7
    line = next(x for x in small.splitlines() if "options (" in x and "Figma (V-112)" in x)
    assert 'selected: "Choose a vendor"' in line
    assert '- option "' not in small
    assert 'combobox "Vendor"' in small and "[ref=" in small  # still actionable


def test_table_rows_become_one_line_and_long_tables_are_cut():
    raw = (FIX / "vendors.txt").read_text()
    small = compact_snapshot(raw)
    assert len(small) < len(raw) * 0.5
    row = next(x for x in small.splitlines() if "BESCOM Private Limited" in x)
    assert '- row: link "V-116" [ref=' in row and "/books/vendors/V-116 | BESCOM |" in row
    many = "- table:\n  - rowgroup [ref=a]:\n" + "".join(
        f'    - row [ref=r{i}]:\n      - cell "{i}" [ref=c{i}]\n' for i in range(40)
    )
    cut = compact_snapshot(many)
    assert cut.count("- row:") == 25 and "15 more rows not shown" in cut


def test_inline_snapshot_replaces_the_file_link(tmp_path):
    (tmp_path / "page.yml").write_text((FIX / "bill_new.txt").read_text())
    result = (
        "### Ran Playwright code\n```js\nawait page.goto('x');\n```\n### Page\n"
        "- Page URL: http://localhost:8101/books/bills/new\n- Page Title: New bill · Books\n"
        "### Snapshot\n- [Snapshot](page.yml)\n"
    )
    text = inline_snapshot(result, tmp_path)
    assert "Ran Playwright code" not in text and "[Snapshot](" not in text
    assert 'combobox "Vendor"' in text
    assert page_of(text) == ("http://localhost:8101/books/bills/new", "New bill · Books")
    assert one_line(text).startswith("[older page snapshot omitted")


def test_strip_code_leaves_errors():
    text = "### Error\nError: Ref e1 not found in the current page snapshot."
    assert strip_code(text) == text
