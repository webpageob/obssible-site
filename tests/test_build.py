"""
Tests for build.py.

The markdown converter is markdown-it-py (CommonMark + GFM tables and
strikethrough), configured with html=False. That configuration is itself a
security decision — see test_raw_html_is_escaped_not_passed_through below —
and is pinned here so a future edit cannot loosen it by accident.
"""

import importlib.util
import json
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


# ---------------------------------------------------------------- sanity


def test_portable_text_renders_headings_lists_marks():
    blocks = [
        {
            "_type": "block",
            "_key": "a1",
            "style": "h2",
            "children": [{"_type": "span", "_key": "a1s", "text": "Sub heading", "marks": []}],
        },
        {
            "_type": "block",
            "_key": "a2",
            "style": "normal",
            "children": [
                {"_type": "span", "_key": "a2s1", "text": "bold", "marks": ["strong"]},
            ],
        },
    ]
    html = build.portable_text_to_html(blocks)
    assert "<h2>Sub heading</h2>" in html
    assert "<strong>bold</strong>" in html


def test_portable_text_empty_input_is_empty_string():
    assert build.portable_text_to_html([]) == ""
    assert build.portable_text_to_html(None) == ""


def test_portable_text_raw_text_is_escaped():
    blocks = [
        {
            "_type": "block",
            "_key": "x1",
            "children": [
                {"_type": "span", "_key": "x1s", "text": "<script>alert(1)</script>", "marks": []}
            ],
        }
    ]
    html = build.portable_text_to_html(blocks)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def _link_block(href):
    return [
        {
            "_type": "block",
            "_key": "l1",
            "children": [{"_type": "span", "_key": "l1s", "text": "click", "marks": ["lk"]}],
            "markDefs": [{"_type": "link", "_key": "lk", "href": href}],
        }
    ]


def test_portable_text_safe_link_is_rendered_as_a_tag():
    html = build.portable_text_to_html(_link_block("https://example.com"))
    assert '<a href="https://example.com">click</a>' in html


@pytest.mark.parametrize(
    "dangerous_href",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        '"><script>alert(1)</script>',
    ],
)
def test_portable_text_dangerous_link_is_not_rendered_as_a_tag(dangerous_href):
    """
    portabletext-html's default link handling was verified directly to trust
    href blindly — no scheme check, no attribute escaping. This is the
    custom serializer in build.py that fixes both.
    """
    html = build.portable_text_to_html(_link_block(dangerous_href))
    assert "<a" not in html
    assert "<script>" not in html


def test_sanity_image_url_has_expected_shape():
    url = build._sanity_image_url("image-abc123DEF-800x600-jpg")
    assert url == (
        "https://cdn.sanity.io/images/%s/%s/abc123DEF-800x600.jpg?w=1600&auto=format"
        % (build.SANITY_PROJECT_ID or "", build.SANITY_DATASET)
    )


def test_sanity_image_url_rejects_malformed_ref():
    assert build._sanity_image_url("not-a-real-ref") is None
    assert build._sanity_image_url("") is None
    assert build._sanity_image_url(None) is None


def test_portable_text_image_renders_img_tag(monkeypatch):
    monkeypatch.setattr(build, "SANITY_PROJECT_ID", "proj123")
    blocks = [
        {
            "_type": "image",
            "_key": "img1",
            "alt": "A cat",
            "asset": {"_ref": "image-abc123-800x600-jpg", "_type": "reference"},
        }
    ]
    html = build.portable_text_to_html(blocks)
    assert "<img" in html
    assert 'alt="A cat"' in html
    assert "cdn.sanity.io/images/proj123" in html


def test_fetch_sanity_posts_returns_empty_list_when_unconfigured(monkeypatch):
    monkeypatch.setattr(build, "SANITY_PROJECT_ID", "")
    assert build.fetch_sanity_posts() == []


def test_fetch_sanity_posts_falls_back_on_network_failure(monkeypatch):
    """The build must never crash because Sanity is unreachable — see the
    module docstring: posts/*.md is the fallback during this migration."""
    monkeypatch.setattr(build, "SANITY_PROJECT_ID", "proj123")

    def _boom(*a, **k):
        raise build.urllib.error.URLError("simulated network failure")

    monkeypatch.setattr(build.urllib.request, "urlopen", _boom)
    assert build.fetch_sanity_posts() == []


def test_fetch_sanity_posts_parses_a_realistic_response(monkeypatch):
    """
    End-to-end: a response shaped like what Sanity's own API actually
    returns (verified format, not guessed) goes in, a post dict shaped
    like parse_post()'s output comes out — so the rest of build.py
    (validation, sorting, RSS, sitemap, templates) needs no special case
    for where a post came from.
    """
    monkeypatch.setattr(build, "SANITY_PROJECT_ID", "proj123")

    fake_response = {
        "result": [
            {
                "_id": "abc123",
                "title": "A Sanity post",
                "slug": "a-sanity-post",
                "date": "2026-08-06",
                "body": [
                    {
                        "_type": "block",
                        "_key": "b1",
                        "style": "normal",
                        "children": [
                            {"_type": "span", "_key": "b1s", "text": "Hello.", "marks": []}
                        ],
                    }
                ],
            },
            {
                # A draft. Public unauthenticated reads should never actually
                # return this, but the defense-in-depth filter must still
                # catch it if one ever slips through.
                "_id": "drafts.def456",
                "title": "Unpublished draft",
                "slug": "unpublished-draft",
                "date": "2026-08-06",
                "body": [],
            },
        ]
    }

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(fake_response).encode("utf-8")

    monkeypatch.setattr(build.urllib.request, "urlopen", lambda *a, **k: _FakeResponse())

    posts = build.fetch_sanity_posts()

    assert len(posts) == 1  # the draft must be excluded
    post = posts[0]
    assert post["slug"] == "a-sanity-post"
    assert post["title"] == "A Sanity post"
    assert post["date"] == "2026-08-06"
    assert "<p>Hello.</p>" in post["body_html"]
    assert "Sanity:" in post["source"]


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
