from radar.collectors.fetch import html_to_text, resolve_google_news
from radar.collectors.google_news import build_url, parse_feed

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Lunar Energy raises $232M to deploy home batteries - TechCrunch</title>
<link>https://news.google.com/rss/articles/CBMiabc?oc=5</link>
<pubDate>Wed, 04 Feb 2026 08:00:00 GMT</pubDate>
<description>&lt;a href="x"&gt;Lunar Energy raises $232M&lt;/a&gt;&amp;nbsp;&lt;font&gt;TechCrunch&lt;/font&gt;</description>
<source url="https://techcrunch.com">TechCrunch</source></item>
<item><title>No link item</title></item>
</channel></rss>"""


def test_parse_feed_strips_source_suffix_and_html():
    items = parse_feed(RSS, "q", 10)
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Lunar Energy raises $232M to deploy home batteries"
    assert it["source"] == "TechCrunch"
    assert it["published_at"] == "2026-02-04T08:00:00+00:00"
    assert it["raw_summary"] == "Lunar Energy raises $232M TechCrunch"
    assert it["query"] == "q"


def test_build_url_encodes_query():
    url = build_url('"Lunar Energy" (funding OR raises)', {"hl": "en-US", "gl": "US", "ceid": "US:en"})
    assert url.startswith("https://news.google.com/rss/search?q=%22Lunar+Energy%22") and "ceid=US%3Aen" in url


def test_html_to_text_prefers_paragraphs():
    html = "<html><head><style>p{}</style><script>var x=1;</script></head><body><nav>Menu Menu Menu</nav>" \
           "<p>" + "Lunar Energy said it raised the round to build batteries. " * 5 + "</p><p>short</p>" \
           "<footer>copyright</footer></body></html>"
    text = html_to_text(html, 200)
    assert text.startswith("Lunar Energy said") and "Menu" not in text and "var x" not in text and len(text) <= 200


def test_non_google_url_passes_through():
    assert resolve_google_news("https://techcrunch.com/x", client=None) == "https://techcrunch.com/x"
