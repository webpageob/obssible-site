#!/usr/bin/env python3
"""
build.py — turns posts/*.md into the /log/ pages, keeps nav + the
homepage "latest log" teaser in sync, and regenerates the RSS feed.
No external packages needed.

Run it every time you add, edit, delete, or rename a file in posts/,
or after editing partials/nav.html:

    python build.py

What it touches:
  - log/index.html          (fully regenerated)
  - log/<slug>.html          (fully regenerated, one per post)
  - log/<old-slug>.html      (deleted, if that post no longer exists)
  - rss.xml                  (fully regenerated — this is what a newsletter
                               service like Buttondown's RSS-to-email would
                               point at; it carries full post content, not
                               just a link)
  - index.html                (only the NAV and LATEST marker blocks)
  - about.html                (only the NAV marker block)

Everything else in index.html / about.html is yours — this script never
touches text outside the marker comments.

See README.md for the full "how do I publish a new post" walkthrough.
"""

import re
import sys
import html as htmllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
POSTS_DIR = ROOT / "posts"
LOG_DIR = ROOT / "log"
PARTIALS_DIR = ROOT / "partials"

# Used only to build absolute links in rss.xml (RSS requires full URLs).
# Change this if the site ever moves to a different domain.
SITE_URL = "https://obssible.com"


# ---------------------------------------------------------------- markdown

def escape(text):
    return htmllib.escape(text, quote=False)


def inline_md(text):
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    return text


def md_to_html(md_text):
    lines = md_text.strip("\n").split("\n")
    blocks = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)

    out = []
    for block in blocks:
        first = block[0]
        if first.startswith("## "):
            out.append("<h4>%s</h4>" % inline_md(first[3:].strip()))
        elif all(l.startswith("> ") or l == ">" for l in block):
            quoted = " ".join(l[2:] if l.startswith("> ") else "" for l in block)
            out.append("<blockquote>%s</blockquote>" % inline_md(quoted.strip()))
        elif all(l.strip().startswith("- ") for l in block):
            items = "".join(
                "<li>%s</li>" % inline_md(l.strip()[2:].strip()) for l in block
            )
            out.append("<ul>%s</ul>" % items)
        else:
            out.append("<p>%s</p>" % inline_md(" ".join(l.strip() for l in block)))
    return "\n".join(out)


# ---------------------------------------------------------------- posts

def parse_post(path):
    text = path.read_text(encoding="utf-8")
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end].strip("\n")
            body = text[end + 4:]
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
    if not date:
        print("  ! %s has no 'date:' in its frontmatter — it will sort last" % path.name)

    return {
        "slug": slug,
        "title": title,
        "date": date,
        "body_html": md_to_html(body),
    }


def load_posts():
    posts = [parse_post(p) for p in sorted(POSTS_DIR.glob("*.md"))]
    posts.sort(key=lambda p: p["date"], reverse=True)
    seen = {}
    for p in posts:
        if p["slug"] in seen:
            print("  ! two posts share the slug '%s' — one will overwrite the other" % p["slug"])
        seen[p["slug"]] = True
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


def inject_marker(text, name, replacement, filename):
    pattern = re.compile(
        r"(<!-- %s:START -->)(.*?)(<!-- %s:END -->)" % (name, name),
        re.DOTALL,
    )
    if not pattern.search(text):
        print(
            "  ⚠ marker %s:START/END not found in %s — nav or the latest-log "
            "preview may be stale. Re-add the <!-- %s:START --> / <!-- %s:END --> "
            "comments (see README.md)." % (name, filename, name, name)
        )
        return text
    return pattern.sub(lambda m: m.group(1) + "\n" + replacement + "\n" + m.group(3), text)


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


def build_sitemap(posts):
    urls = [
        ("%s/" % SITE_URL, None),
        ("%s/about.html" % SITE_URL, None),
        ("%s/log/" % SITE_URL, None),
    ]
    for p in posts:
        urls.append(("%s/log/%s.html" % (SITE_URL, p["slug"]), p["date"]))

    entries = []
    for loc, lastmod in urls:
        if lastmod:
            entries.append("  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n  </url>" % (loc, lastmod))
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
        link = "%s/log/%s.html" % (SITE_URL, p["slug"])
        items.append(
            "  <item>\n"
            "    <title>%s</title>\n"
            "    <link>%s</link>\n"
            "    <guid>%s</guid>\n"
            "    <pubDate>%s</pubDate>\n"
            "    <description>%s</description>\n"
            "    <content:encoded>%s</content:encoded>\n"
            "  </item>" % (
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

def main():
    nav_raw = (PARTIALS_DIR / "nav.html").read_text(encoding="utf-8").strip()
    post_tpl = (PARTIALS_DIR / "post-template.html").read_text(encoding="utf-8")
    list_tpl = (PARTIALS_DIR / "list-template.html").read_text(encoding="utf-8")

    posts = load_posts()
    print("Found %d post(s) in posts/" % len(posts))

    # ---- remove log/*.html pages whose post no longer exists ----
    valid_slugs = {p["slug"] for p in posts}
    for existing in LOG_DIR.glob("*.html"):
        if existing.stem != "index" and existing.stem not in valid_slugs:
            existing.unlink()
            print("  removed log/%s.html (no matching post)" % existing.stem)

    # ---- log/<slug>.html, one per post ----
    for post in posts:
        post_url = "%s/log/%s.html" % (SITE_URL, post["slug"])
        page = post_tpl
        page = page.replace("{{NAV}}", render_nav(nav_raw, "/log/%s.html" % post["slug"]))
        page = page.replace("{{TITLE}}", escape(post["title"]))
        page = page.replace("{{DATE}}", escape(post["date"]))
        page = page.replace("{{BODY}}", post["body_html"])
        page = page.replace("{{DESCRIPTION}}", escape(plain_excerpt(post["body_html"])))
        page = page.replace("{{URL}}", post_url)
        out_path = LOG_DIR / ("%s.html" % post["slug"])
        out_path.write_text(page, encoding="utf-8")
        print("  wrote log/%s.html" % post["slug"])

    # ---- log/index.html ----
    if posts:
        items = "\n".join(
            '    <li><a href="%s.html"><span class="log-list-date">%s</span>'
            '<span class="log-list-title">%s</span></a></li>'
            % (p["slug"], escape(p["date"]), escape(p["title"]))
            for p in posts
        )
    else:
        items = '    <li><span class="log-list-date">—</span>'\
                '<span class="log-list-title">No logs yet.</span></li>'
    list_page = list_tpl.replace("{{NAV}}", render_nav(nav_raw, "/log/"))
    list_page = list_page.replace("{{ITEMS}}", items)
    (LOG_DIR / "index.html").write_text(list_page, encoding="utf-8")
    print("  wrote log/index.html")

    # ---- rss.xml ----
    (ROOT / "rss.xml").write_text(build_rss(posts), encoding="utf-8")
    print("  wrote rss.xml (%d item%s)" % (len(posts), "" if len(posts) == 1 else "s"))

    old_feed = ROOT / "feed.xml"
    if old_feed.exists():
        old_feed.unlink()
        print("  removed feed.xml (replaced by rss.xml)")

    # ---- sitemap.xml ----
    (ROOT / "sitemap.xml").write_text(build_sitemap(posts), encoding="utf-8")
    print("  wrote sitemap.xml")

    # ---- index.html: NAV + LATEST markers ----
    index_path = ROOT / "index.html"
    index_text = index_path.read_text(encoding="utf-8")
    index_text = inject_marker(index_text, "NAV", render_nav(nav_raw, "/"), "index.html")
    if posts:
        latest = posts[0]
        latest_html = (
            '<p><a href="log/%s.html">%s</a></p>\n'
            '<p class="status">%s — <a href="log/">See all logs →</a></p>'
            % (latest["slug"], escape(latest["title"]), escape(latest["date"]))
        )
    else:
        latest_html = '<p><a href="log/">See all logs →</a></p>'
    index_text = inject_marker(index_text, "LATEST", latest_html, "index.html")
    index_path.write_text(index_text, encoding="utf-8")
    print("  updated index.html (nav + latest)")

    # ---- about.html: NAV marker only ----
    about_path = ROOT / "about.html"
    if about_path.exists():
        about_text = about_path.read_text(encoding="utf-8")
        about_text = inject_marker(about_text, "NAV", render_nav(nav_raw, "/about.html"), "about.html")
        about_path.write_text(about_text, encoding="utf-8")
        print("  updated about.html (nav)")

    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
