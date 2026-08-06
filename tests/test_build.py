"""
Tests for build.py.

The markdown converter is markdown-it-py (CommonMark + GFM tables and
strikethrough), configured with html=False. That configuration is itself a
security decision — see test_raw_html_is_escaped_not_passed_through below —
and is pinned here so a future edit cannot loosen it by accident.
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


# ---------------------------------------------------------------- markdown


@pytest.mark.parametrize(
    "label,source,expected",
    [
        ("h1", "# Big", "<h1>Big</h1>"),
        ("h2", "## Sub heading", "<h2>Sub heading</h2>"),
        ("h3", "### Small", "<h3>Small</h3>"),
        ("paragraph", "Just a paragraph.", "<p>Just a paragraph.</p>"),
        ("bold", "**bold**", "<p><strong>bold</strong></p>"),
        ("italic", "*italic*", "<p><em>italic</em></p>"),
        ("inline code", "`code`", "<p><code>code</code></p>"),
        (
            "link",
            "[text](https://example.com)",
            '<p><a href="https://example.com">text</a></p>',
        ),
        ("unordered list", "- one\n- two", "<ul>\n<li>one</li>\n<li>two</li>\n</ul>"),
        (
            "ordered list",
            "1. first\n2. second",
            "<ol>\n<li>first</li>\n<li>second</li>\n</ol>",
        ),
        (
            "nested list",
            "- top\n  - nested",
            "<ul>\n<li>top\n<ul>\n<li>nested</li>\n</ul>\n</li>\n</ul>",
        ),
        # CommonMark wraps blockquote text in <p> — this is spec-correct, not a bug.
        ("blockquote", "> quoted", "<blockquote>\n<p>quoted</p>\n</blockquote>"),
        ("image", "![cat](/img/cat.png)", '<p><img src="/img/cat.png" alt="cat" /></p>'),
        (
            "table",
            "| a | b |\n|---|---|\n| 1 | 2 |",
            "<table>\n<thead>\n<tr>\n<th>a</th>\n<th>b</th>\n</tr>\n</thead>\n"
            "<tbody>\n<tr>\n<td>1</td>\n<td>2</td>\n</tr>\n</tbody>\n</table>",
        ),
        ("horizontal rule (dashes)", "---", "<hr />"),
        ("horizontal rule (stars)", "***", "<hr />"),
        ("strikethrough", "~~gone~~", "<p><s>gone</s></p>"),
        ("fenced code block", "```\nprint(1)\n```", "<pre><code>print(1)\n</code></pre>"),
    ],
)
def test_supported_markdown(label, source, expected):
    assert build.md_to_html(source) == expected


def test_paragraphs_are_separated_by_blank_lines():
    assert build.md_to_html("one\n\ntwo") == "<p>one</p>\n<p>two</p>"


def test_task_lists_are_not_enabled():
    """
    Not a bug: GFM task-list checkboxes need a separate plugin this project
    does not install. "- [ ] todo" renders as a normal list item with the
    brackets as literal text. Documented here so it reads as a deliberate
    scope boundary, not a regression, if someone tries it and it looks odd.
    """
    assert build.md_to_html("- [ ] todo") == "<ul>\n<li>[ ] todo</li>\n</ul>"


# ----------------------------------------------------------------- security


def test_raw_html_is_escaped_not_passed_through():
    """
    CommonMark allows raw HTML passthrough by default. This project disables
    that (html=False in build.py) specifically so a pasted <script> tag
    cannot reach production unescaped.
    """
    assert (
        build.md_to_html("<script>alert(1)</script>")
        == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
    )


def test_javascript_url_is_not_rendered_as_a_link():
    rendered = build.md_to_html("[click](javascript:alert(1))")
    assert "<a" not in rendered
    assert "javascript:" not in rendered or "href" not in rendered


def test_data_url_is_not_rendered_as_a_link():
    rendered = build.md_to_html("[click](data:text/html,<script>alert(1)</script>)")
    assert 'href="data:' not in rendered


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
