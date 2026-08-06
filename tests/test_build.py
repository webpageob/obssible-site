"""
Tests for build.py.

The markdown tests below are deliberately split in two:

  - What the converter supports today, pinned so it cannot silently regress.
  - What it does NOT support, recorded exactly as it currently behaves.

That second group is the Phase 0 audit finding: a browser CMS emits all of
this, and today the converter turns it into visibly wrong output without
raising an error. Phase 2 fixes that. When it does, those tests get rewritten
to assert correct output instead — they are here so the damage is visible and
cannot be forgotten.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
sys.modules["build"] = build
spec.loader.exec_module(build)


# ---------------------------------------------------------------- supported


@pytest.mark.parametrize(
    "source,expected",
    [
        ("## Sub heading", "<h2>Sub heading</h2>"),
        ("Just a paragraph.", "<p>Just a paragraph.</p>"),
        ("- one\n- two", "<ul><li>one</li><li>two</li></ul>"),
        ("> quoted", "<blockquote>quoted</blockquote>"),
        ("**bold**", "<p><strong>bold</strong></p>"),
        ("*italic*", "<p><em>italic</em></p>"),
        ("`code`", "<p><code>code</code></p>"),
        ("[text](https://example.com)", '<p><a href="https://example.com">text</a></p>'),
    ],
)
def test_supported_markdown(source, expected):
    assert build.md_to_html(source) == expected


def test_paragraphs_are_separated_by_blank_lines():
    assert build.md_to_html("one\n\ntwo") == "<p>one</p>\n<p>two</p>"


def test_html_in_content_is_escaped():
    assert "&lt;script&gt;" in build.md_to_html("<script>alert(1)</script>")


# ------------------------------------------------------- NOT supported yet


@pytest.mark.parametrize(
    "label,source,current_broken_output",
    [
        ("h1", "# Big", "<p># Big</p>"),
        ("h3", "### Small", "<p>### Small</p>"),
        ("ordered list", "1. first\n2. second", "<p>1. first 2. second</p>"),
        ("image", "![cat](/img/cat.png)", '<p>!<a href="/img/cat.png">cat</a></p>'),
        ("table", "| a | b |", "<p>| a | b |</p>"),
        ("horizontal rule", "***", "<p>***</p>"),
        ("strikethrough", "~~gone~~", "<p>~~gone~~</p>"),
        ("task list", "- [ ] todo", "<ul><li>[ ] todo</li></ul>"),
    ],
)
def test_unsupported_markdown_is_currently_mangled(label, source, current_broken_output):
    """Phase 0 finding, pinned. Phase 2 must make these either correct or loud."""
    assert build.md_to_html(source) == current_broken_output


def test_image_does_not_produce_an_img_tag_yet():
    """The single most dangerous gap: CMS image upload would render broken."""
    assert "<img" not in build.md_to_html("![cat](/img/cat.png)")


# ---------------------------------------------------------------- posts


def test_frontmatter_is_parsed(tmp_path):
    post = tmp_path / "whatever-filename.md"
    post.write_text(
        "---\ntitle: My Title\ndate: 2026-01-02\nslug: my-slug\n---\nBody text.",
        encoding="utf-8",
    )
    parsed = build.parse_post(post)
    assert parsed["title"] == "My Title"
    assert parsed["date"] == "2026-01-02"
    assert parsed["slug"] == "my-slug"
    assert "<p>Body text.</p>" in parsed["body_html"]


def _post(source, slug="s", title="T", date="2026-01-01"):
    return {"source": source, "slug": slug, "title": title, "date": date, "body_html": ""}


def test_valid_posts_pass_validation():
    build.validate_posts([_post("a.md", slug="a"), _post("b.md", slug="b")])


def test_duplicate_slugs_fail_the_build():
    """Two posts with one slug means one silently overwrites the other."""
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a.md", slug="same"), _post("b.md", slug="same")])
    message = str(exc.value)
    assert "same" in message
    assert "a.md" in message and "b.md" in message


def test_missing_date_fails_the_build():
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a.md", date="")])
    assert "no 'date:'" in str(exc.value)


@pytest.mark.parametrize("bad_date", ["Aug 6 2026", "2026/08/06", "6-8-2026", "2026-8-6"])
def test_malformed_date_fails_the_build(bad_date):
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a.md", date=bad_date)])
    assert "must look like" in str(exc.value)


def test_missing_title_fails_the_build():
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a.md", title="")])
    assert "no 'title:'" in str(exc.value)


def test_all_problems_are_reported_at_once():
    """One build run should list every problem, not just the first."""
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a.md", slug="x", date=""), _post("b.md", slug="x")])
    message = str(exc.value)
    assert "no 'date:'" in message
    assert "slugs must be unique" in message


def test_slug_falls_back_to_filename_when_missing(tmp_path):
    post = tmp_path / "fallback-name.md"
    post.write_text("---\ntitle: T\ndate: 2026-01-01\n---\nBody.", encoding="utf-8")
    assert build.parse_post(post)["slug"] == "fallback-name"


@pytest.mark.parametrize("bad", ["../escape", "with/slash", "back\\slash"])
def test_dangerous_slugs_are_rejected(tmp_path, bad):
    post = tmp_path / "safe-name.md"
    post.write_text("---\ntitle: T\ndate: 2026-01-01\nslug: %s\n---\nBody." % bad, encoding="utf-8")
    assert build.parse_post(post)["slug"] == "safe-name"


# ---------------------------------------------------------------- urls


def test_post_url_is_the_locked_directory_form():
    assert build.post_url("my-post") == "https://obssible.com/log/my-post/"


def test_post_url_has_no_html_extension():
    """Locked 2026-08-06. Changing this breaks shared links and newsletter dedup."""
    assert not build.post_url("my-post").endswith(".html")


# ---------------------------------------------------------------- templates


def test_unfilled_placeholder_fails_the_build():
    with pytest.raises(SystemExit) as exc:
        build.fill("<p>{{TITLE}} and {{MISSING}}</p>", {"TITLE": "x"}, "demo.html")
    assert "MISSING" in str(exc.value)


def test_fill_substitutes_every_token():
    assert build.fill("{{A}}-{{B}}", {"A": "1", "B": "2"}, "demo.html") == "1-2"


# ---------------------------------------------------------------- nav


def test_nav_marks_the_current_page():
    nav = '<a href="/">Home</a><a href="/log/">Log</a>'
    assert 'href="/" class="current"' in build.render_nav(nav, "/")


def test_nav_marks_log_section_for_a_post_page():
    nav = '<a href="/">Home</a><a href="/log/">Log</a>'
    rendered = build.render_nav(nav, "/log/some-post/")
    assert 'href="/log/" class="current"' in rendered
    assert 'href="/" class="current"' not in rendered
