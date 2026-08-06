#!/usr/bin/env python3
"""
build.py — turns posts into the /log/ pages, keeps nav + the homepage
"latest log" teaser in sync, and regenerates the RSS feed.

TRANSITIONAL STATE (started 2026-08-06): posts can come from TWO places
at once — local posts/*.md files, and Sanity (a hosted CMS). This is
deliberate, not an oversight. Sanity is the CMS being migrated to, but
until it is fully verified in production, posts/*.md stays live as a
working fallback — the project must never be left without a way to
publish. Once Sanity has been used for real, working posts and that is
confirmed end to end, posts/*.md and this note get removed in a separate
change. See README.md.

Needs two packages: markdown-it-py and portabletext-html (see
requirements.txt). Everything else is the standard library — including
the Sanity fetch, which is a plain HTTP GET, no SDK.

Run it every time you add, edit, delete, or rename a file in posts/,
after publishing in Sanity, or after editing partials/nav.html:

    python build.py

SOURCE (edit these):
  - posts/*.md                 your writing (legacy path, see note above)
  - Sanity Studio               your writing (new path)
  - partials/*.html            page templates and the shared nav
  - assets/style.css           all styling

GENERATED (never edit — wiped and rewritten on every build):
  - index.html                 from partials/home-template.html
  - about.html                 from partials/about-template.html
  - log/index.html             the post list
  - log/<slug>/index.html      one directory per post
  - rss.xml                    full post content, for RSS-to-email
  - sitemap.xml

Post URLs are permanent: https://obssible.com/log/<slug>/
Locked 2026-08-06. The RSS <guid> is this URL and the newsletter service
uses it to decide what has already been sent — changing it would break
shared links and can cause duplicate sends.

See README.md for the full "how do I publish a new post" walkthrough.
"""

import html as htmllib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from markdown_it import MarkdownIt
from portabletext_html import PortableTextRenderer
from portabletext_html.marker_definitions import LinkMarkerDefinition

ROOT = Path(__file__).parent
POSTS_DIR = ROOT / "posts"
LOG_DIR = ROOT / "log"
PARTIALS_DIR = ROOT / "partials"

# On a Korean Windows install the console defaults to cp949, which cannot print
# the em dashes this script uses in its warnings. Without this, a post with bad
# frontmatter crashes the build with an encoding traceback instead of showing
# the warning that explains what is wrong.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Used only to build absolute links in rss.xml (RSS requires full URLs).
# Change this if the site ever moves to a different domain.
SITE_URL = "https://obssible.com"


# ---------------------------------------------------------------- markdown

# CommonMark + GFM tables/strikethrough. This covers everything a rich-text
# CMS editor (Sveltia, Decap) can realistically emit — headings, lists
# (ordered, unordered, nested), images, tables, code blocks, rules,
# blockquotes, strikethrough, links, bold/italic.
#
# html=False is a deliberate, security-relevant choice: CommonMark allows raw
# HTML passthrough by default, which would let a pasted <script> tag reach
# production unescaped. This makes the parser treat raw HTML as plain text,
# same as the parser it replaces.
_md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def escape(text):
    return htmllib.escape(text, quote=False)


def md_to_html(md_text):
    # .strip() drops the single trailing newline markdown-it always emits,
    # so output matches what the rest of build.py (and its tests) expect.
    return _md.render(md_text).strip()


# ---------------------------------------------------------------- posts


def parse_post(path):
    text = path.read_text(encoding="utf-8")
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end].strip("\n")
            body = text[end + 4 :]
            for line in front.split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip().lower()] = val.strip()

    slug = meta.get("slug", "").strip()
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        if slug:
            print("  ! bad slug in %s, using filename instead" % path.name)
        slug = path.stem

    title = meta.get("title", slug)
    date = meta.get("date", "")

    return {
        "slug": slug,
        "title": title,
        "date": date,
        "body_html": md_to_html(body),
        "source": path.name,
    }


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_posts(posts):
    """Reject anything that would silently produce wrong output.

    These are hard failures, not warnings. A duplicate slug overwrites a real
    post and loses it; a missing or malformed date sorts unpredictably and
    renders blank. Both are invisible once published, so the build stops here.
    """
    problems = []

    for post in posts:
        if not post["date"]:
            problems.append("%s has no 'date:' in its frontmatter" % post["source"])
        elif not DATE_PATTERN.match(post["date"]):
            problems.append(
                "%s has date '%s' — it must look like 2026-08-06" % (post["source"], post["date"])
            )
        if not post["title"]:
            problems.append("%s has no 'title:' in its frontmatter" % post["source"])

    by_slug = {}
    for post in posts:
        by_slug.setdefault(post["slug"], []).append(post["source"])
    for slug, sources in sorted(by_slug.items()):
        if len(sources) > 1:
            problems.append(
                "slug '%s' is used by %d files (%s) — slugs must be unique, "
                "otherwise one post overwrites the other"
                % (slug, len(sources), ", ".join(sorted(sources)))
            )

    if problems:
        raise SystemExit(
            "BUILD FAILED — fix these before publishing:\n"
            + "\n".join("  - %s" % p for p in problems)
        )


# ---------------------------------------------------------------- sanity
#
# Sanity stores content in its own cloud database ("Content Lake"), not in
# this repo — build.py fetches it at build time over plain HTTP. No SDK,
# and no secret is needed to read: the dataset is public, and Sanity's
# documented behavior is that unauthenticated reads of a public dataset
# automatically exclude drafts (their _id is prefixed "drafts."). The
# explicit filter below is defense in depth in case that ever changes
# (e.g. if a token gets added to this query later).
#
# If SANITY_PROJECT_ID isn't set, or the request fails for any reason,
# this returns an empty list rather than raising. During this transitional
# period that is correct: the build must fall back to posts/*.md, not
# fail. Once posts/*.md is removed (see the module docstring), a fetch
# failure should become fatal instead — that change belongs with that step.

SANITY_PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "").strip()
SANITY_DATASET = os.environ.get("SANITY_DATASET", "production").strip()
SANITY_API_VERSION = "2024-01-01"  # pinned for stability, like requirements.txt

_SAFE_URL_SCHEMES = ("http://", "https://", "mailto:")


class _SafeLinkMarkerDefinition(LinkMarkerDefinition):
    """
    Replaces portabletext-html's default link renderer. Verified directly
    that the default trusts href completely: no scheme check (a
    javascript: URL renders as a real, clickable link) and no attribute
    escaping (a crafted href can break out of the href="..." attribute).
    This gives Sanity-sourced links the same safety property the
    markdown-it-py path already has.
    """

    @classmethod
    def _href(cls, marker, context):
        marker_definition = next((md for md in context.markDefs if md["_key"] == marker), None)
        return (marker_definition or {}).get("href", "") or ""

    @classmethod
    def render_prefix(cls, span, marker, context):
        href = cls._href(marker, context)
        if not href.startswith(_SAFE_URL_SCHEMES):
            return "<span>"
        return '<a href="%s">' % htmllib.escape(href, quote=True)

    @classmethod
    def render_suffix(cls, span, marker, context):
        href = cls._href(marker, context)
        return "</a>" if href.startswith(_SAFE_URL_SCHEMES) else "</span>"


# Sanity encodes an image's id, size, and format into its asset reference:
# "image-<hash>-<width>x<height>-<format>". Verified against Sanity's docs
# rather than assumed — getting this wrong means every image breaks.
_IMAGE_REF_PATTERN = re.compile(r"^image-([a-zA-Z0-9]+)-(\d+x\d+)-(\w+)$")


def _sanity_image_url(ref, max_width=1600):
    match = _IMAGE_REF_PATTERN.match(ref or "")
    if not match:
        return None
    asset_hash, dims, fmt = match.groups()
    # max_width caps what gets downloaded — the free plan's bandwidth is
    # limited, and nothing in this design needs a full-resolution original.
    return "https://cdn.sanity.io/images/%s/%s/%s-%s.%s?w=%d&auto=format" % (
        SANITY_PROJECT_ID,
        SANITY_DATASET,
        asset_hash,
        dims,
        fmt,
        max_width,
    )


def _render_sanity_image(node, *_args):
    url = _sanity_image_url((node.get("asset") or {}).get("_ref"))
    if not url:
        return ""
    alt = htmllib.escape(node.get("alt", "") or "", quote=True)
    return '<img src="%s" alt="%s">' % (htmllib.escape(url, quote=True), alt)


def portable_text_to_html(blocks):
    """Render Sanity's rich-text format (a list of block objects) to HTML."""
    if not blocks:
        return ""
    renderer = PortableTextRenderer(
        blocks,
        custom_marker_definitions={"link": _SafeLinkMarkerDefinition},
        custom_serializers={"image": _render_sanity_image},
    )
    # The library always wraps multi-block output in <div>...</div> and
    # exposes no constructor option to turn that off — only this attribute.
    renderer._wrapper_element = ""
    return renderer.render().strip()


def fetch_sanity_posts():
    if not SANITY_PROJECT_ID:
        print("  Sanity: not configured (SANITY_PROJECT_ID unset) — posts/*.md only")
        return []

    query = '*[_type == "post"] | order(date desc){ _id, title, "slug": slug.current, date, body }'
    url = "https://%s.apicdn.sanity.io/v%s/data/query/%s?query=%s" % (
        SANITY_PROJECT_ID,
        SANITY_API_VERSION,
        SANITY_DATASET,
        urllib.parse.quote(query),
    )

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print("  ! could not reach Sanity (%s) — continuing with posts/*.md only" % exc)
        return []

    posts = []
    for raw in payload.get("result", []):
        if str(raw.get("_id", "")).startswith("drafts."):
            continue
        title = (raw.get("title") or "").strip()
        posts.append(
            {
                "slug": (raw.get("slug") or "").strip(),
                "title": title,
                "date": (raw.get("date") or "").strip(),
                "body_html": portable_text_to_html(raw.get("body")),
                "source": "Sanity: %s" % (title or raw.get("slug") or "untitled"),
            }
        )
    print("  Sanity: fetched %d post(s)" % len(posts))
    return posts


def load_posts():
    posts = [parse_post(p) for p in sorted(POSTS_DIR.glob("*.md"))]
    posts += fetch_sanity_posts()
    validate_posts(posts)
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


# ---------------------------------------------------------------- nav


def render_nav(nav_html, current_path):
    def mark(m):
        href = m.group(1)
        if href == "/":
            is_current = current_path == "/"
        elif href.endswith("/"):
            is_current = current_path.startswith(href)
        else:
            is_current = current_path == href
        if is_current:
            return '<a href="%s" class="current">' % href
        return m.group(0)

    return re.sub(r'<a href="([^"]+)">', mark, nav_html)


def fill(template, values, template_name):
    """Substitute {{TOKEN}} placeholders. Fails loudly if any are left over."""
    out = template
    for key, value in values.items():
        out = out.replace("{{%s}}" % key, value)
    leftover = re.findall(r"\{\{([A-Z_]+)\}\}", out)
    if leftover:
        raise SystemExit(
            "BUILD FAILED: %s has unfilled placeholder(s): %s"
            % (template_name, ", ".join(sorted(set(leftover))))
        )
    return out


# ---------------------------------------------------------------- rss


def rfc822_date(date_str=None):
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def plain_excerpt(body_html, max_chars=200):
    """Strip tags to make a short plain-text summary for <description>."""
    text = re.sub(r"<[^>]+>", " ", body_html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + "…"


def cdata(html_content):
    # "]]>" can't appear literally inside a CDATA block — split it if it does.
    safe = html_content.replace("]]>", "]]]]><![CDATA[>")
    return "<![CDATA[%s]]>" % safe


def post_url(slug):
    """The permanent public URL for a post. Locked 2026-08-06 — see README."""
    return "%s/log/%s/" % (SITE_URL, slug)


def build_sitemap(posts):
    urls = [
        ("%s/" % SITE_URL, None),
        ("%s/about.html" % SITE_URL, None),
        ("%s/log/" % SITE_URL, None),
    ]
    for p in posts:
        urls.append((post_url(p["slug"]), p["date"]))

    entries = []
    for loc, lastmod in urls:
        if lastmod:
            entries.append(
                "  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n  </url>" % (loc, lastmod)
            )
        else:
            entries.append("  <url>\n    <loc>%s</loc>\n  </url>" % loc)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "%s\n"
        "</urlset>\n" % "\n".join(entries)
    )


def build_rss(posts):
    items = []
    for p in posts:
        link = post_url(p["slug"])
        items.append(
            "  <item>\n"
            "    <title>%s</title>\n"
            "    <link>%s</link>\n"
            "    <guid>%s</guid>\n"
            "    <pubDate>%s</pubDate>\n"
            "    <description>%s</description>\n"
            "    <content:encoded>%s</content:encoded>\n"
            "  </item>"
            % (
                escape(p["title"]),
                link,
                link,
                rfc822_date(p["date"]),
                escape(plain_excerpt(p["body_html"])),
                cdata(p["body_html"]),
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">\n'
        "<channel>\n"
        "  <title>Junwoo — Log</title>\n"
        "  <link>%s/log/</link>\n"
        "  <description>Every immersion session, published as it happens.</description>\n"
        "  <language>en</language>\n"
        "  <lastBuildDate>%s</lastBuildDate>\n"
        "%s\n"
        "</channel>\n"
        "</rss>\n" % (SITE_URL, rfc822_date(), "\n".join(items))
    )


# ---------------------------------------------------------------- main


def clean_generated():
    """Delete previously generated output so stale files can never linger."""
    if LOG_DIR.exists():
        shutil.rmtree(LOG_DIR)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "about.html", "rss.xml", "sitemap.xml", "feed.xml"):
        target = ROOT / name
        if target.exists():
            target.unlink()


def main():
    nav_raw = (PARTIALS_DIR / "nav.html").read_text(encoding="utf-8").strip()
    post_tpl = (PARTIALS_DIR / "post-template.html").read_text(encoding="utf-8")
    list_tpl = (PARTIALS_DIR / "list-template.html").read_text(encoding="utf-8")
    home_tpl = (PARTIALS_DIR / "home-template.html").read_text(encoding="utf-8")
    about_tpl = (PARTIALS_DIR / "about-template.html").read_text(encoding="utf-8")

    posts = load_posts()
    print("Found %d post(s) total" % len(posts))

    clean_generated()

    # ---- log/<slug>/index.html, one directory per post ----
    for post in posts:
        slug = post["slug"]
        page = fill(
            post_tpl,
            {
                "NAV": render_nav(nav_raw, "/log/%s/" % slug),
                "TITLE": escape(post["title"]),
                "DATE": escape(post["date"]),
                "BODY": post["body_html"],
                "DESCRIPTION": escape(plain_excerpt(post["body_html"])),
                "URL": post_url(slug),
            },
            "post-template.html",
        )
        out_dir = LOG_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(page, encoding="utf-8")
        print("  wrote log/%s/index.html" % slug)

    # ---- log/index.html ----
    if posts:
        items = "\n".join(
            '    <li><a href="/log/%s/"><span class="log-list-date">%s</span>'
            '<span class="log-list-title">%s</span></a></li>'
            % (p["slug"], escape(p["date"]), escape(p["title"]))
            for p in posts
        )
    else:
        items = (
            '    <li><span class="log-list-date">—</span>'
            '<span class="log-list-title">No logs yet.</span></li>'
        )
    (LOG_DIR / "index.html").write_text(
        fill(
            list_tpl,
            {"NAV": render_nav(nav_raw, "/log/"), "ITEMS": items},
            "list-template.html",
        ),
        encoding="utf-8",
    )
    print("  wrote log/index.html")

    # ---- rss.xml ----
    (ROOT / "rss.xml").write_text(build_rss(posts), encoding="utf-8")
    print("  wrote rss.xml (%d item%s)" % (len(posts), "" if len(posts) == 1 else "s"))

    # ---- sitemap.xml ----
    (ROOT / "sitemap.xml").write_text(build_sitemap(posts), encoding="utf-8")
    print("  wrote sitemap.xml")

    # ---- index.html ----
    if posts:
        latest = posts[0]
        latest_html = (
            '  <p><a href="/log/%s/">%s</a></p>\n'
            '  <p class="status">%s — <a href="/log/">See all logs →</a></p>'
            % (latest["slug"], escape(latest["title"]), escape(latest["date"]))
        )
    else:
        latest_html = '  <p><a href="/log/">See all logs →</a></p>'
    (ROOT / "index.html").write_text(
        fill(
            home_tpl,
            {"NAV": render_nav(nav_raw, "/"), "LATEST": latest_html},
            "home-template.html",
        ),
        encoding="utf-8",
    )
    print("  wrote index.html")

    # ---- about.html ----
    (ROOT / "about.html").write_text(
        fill(about_tpl, {"NAV": render_nav(nav_raw, "/about.html")}, "about-template.html"),
        encoding="utf-8",
    )
    print("  wrote about.html")

    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
