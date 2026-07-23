from anime_rss.modules.feeds.adapters import FeedDocumentParser


def test_rss_is_normalized_without_using_description() -> None:
    body = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test</title>
      <item>
        <guid>episode-1</guid>
        <title>  [Group] Anime&#x3000;Name - 01  </title>
        <description><![CDATA[<script src="https://bad.test/x"></script>]]></description>
        <enclosure
          url="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
          type="application/x-bittorrent" />
        <pubDate>Tue, 21 Jul 2026 10:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    entries = FeedDocumentParser().parse(body)

    assert len(entries) == 1
    assert entries[0].title_normalized == "[Group] Anime Name - 01"
    assert entries[0].torrent_reference is not None
    assert "bad.test" not in entries[0].torrent_reference


def test_malformed_url_does_not_abort_other_feed_entries() -> None:
    body = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test</title>
      <item><guid>bad</guid><title>Bad</title>
        <link>https://[broken</link>
      </item>
      <item><guid>good</guid><title>Good</title>
        <link>https://example.test/page</link>
      </item>
    </channel></rss>"""

    entries = FeedDocumentParser().parse(body)

    assert [entry.source_guid for entry in entries] == ["bad", "good"]
    assert entries[0].torrent_reference is None
    assert entries[1].link == "https://example.test/page"
