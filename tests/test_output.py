from scribe import output


def test_sanitize_strips_illegal_and_trims():
    assert output.sanitize('a/b:c*?"<>|d') == "a b c d"
    assert output.sanitize("  ...trailing.  ") == "trailing"
    assert output.sanitize("") == "untitled"


def test_output_path_layout():
    p = output.output_path("/base", "Some Channel", "20260101", "My Title", "txt")
    assert p == "/base/Some Channel/2026-01-01 My Title.txt"


def test_output_path_missing_date():
    p = output.output_path("/base", None, None, "T", "md")
    assert p == "/base/unknown/T.md"


def test_write_no_clobber(tmp_path):
    p = str(tmp_path / "x.txt")
    a = output.write_no_clobber(p, "first")
    b = output.write_no_clobber(p, "second")
    assert a == p
    assert b == str(tmp_path / "x (2).txt")
    assert open(a).read() == "first" and open(b).read() == "second"
