"""
Tests for build.py.

Posts come from Sanity, rendered from Portable Text via portabletext-html
with a custom link serializer (see test_portable_text_dangerous_link_is_not_rendered_as_a_tag
below) that closes an href-injection hole the library's default doesn't.
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


def test_fetch_sanity_posts_fails_the_build_on_network_failure(monkeypatch):
    """
    There is no posts/*.md fallback anymore — if a project ID is configured
    but Sanity can't be reached, the build must stop loudly, not deploy a
    site silently missing content.
    """
    monkeypatch.setattr(build, "SANITY_PROJECT_ID", "proj123")

    def _boom(*a, **k):
        raise build.urllib.error.URLError("simulated network failure")

    monkeypatch.setattr(build.urllib.request, "urlopen", _boom)
    with pytest.raises(SystemExit) as exc:
        build.fetch_sanity_posts()
    assert "simulated network failure" in str(exc.value)


def test_fetch_sanity_posts_parses_a_realistic_response(monkeypatch):
    """
    End-to-end: a response shaped like what Sanity's own API actually
    returns (verified format, not guessed) goes in, the same post-dict
    shape validate_posts()/build_rss()/build_sitemap() expect comes out.
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


def _post(source, slug="s", title="T", date="2026-01-01"):
    return {"source": source, "slug": slug, "title": title, "date": date, "body_html": ""}


def test_valid_posts_pass_validation():
    build.validate_posts([_post("a", slug="a"), _post("b", slug="b")])


def test_duplicate_slugs_fail_the_build():
    """Two posts with one slug means one silently overwrites the other."""
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a", slug="same"), _post("b", slug="same")])
    message = str(exc.value)
    assert "same" in message
    assert "a" in message and "b" in message


def test_missing_date_fails_the_build():
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a", date="")])
    assert "no date" in str(exc.value)


@pytest.mark.parametrize("bad_date", ["Aug 6 2026", "2026/08/06", "6-8-2026", "2026-8-6"])
def test_malformed_date_fails_the_build(bad_date):
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a", date=bad_date)])
    assert "must look like" in str(exc.value)


def test_missing_title_fails_the_build():
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a", title="")])
    assert "no title" in str(exc.value)


def test_missing_slug_fails_the_build():
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a", slug="")])
    assert "no slug" in str(exc.value)


@pytest.mark.parametrize("bad", ["../escape", "with/slash", "back\\slash"])
def test_unsafe_slug_fails_the_build(bad):
    """
    Sanity's slug field has no format restriction beyond being required, so
    a manually-typed slug could contain path-traversal characters. Nothing
    else in build.py checks this before using the slug as a directory name
    (out_dir = LOG_DIR / slug) — this is the only guard.
    """
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a", slug=bad)])
    assert "unsafe slug" in str(exc.value)


def test_all_problems_are_reported_at_once():
    """One build run should list every problem, not just the first."""
    with pytest.raises(SystemExit) as exc:
        build.validate_posts([_post("a", slug="x", date=""), _post("b", slug="x")])
    message = str(exc.value)
    assert "no date" in message
    assert "slugs must be unique" in message


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
