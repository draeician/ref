"""Tests for YouTube community post handling and video extraction."""

import json

from ref_cli import cli


def _post_html_with_video(video_id: str) -> str:
    initial_data = {
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [
                    {
                        "tabRenderer": {
                            "content": {
                                "sectionListRenderer": {
                                    "contents": [
                                        {
                                            "itemSectionRenderer": {
                                                "contents": [
                                                    {
                                                        "backstagePostThreadRenderer": {
                                                            "post": {
                                                                "backstagePostRenderer": {
                                                                    "postId": "Ugkx123",
                                                                    "backstageAttachment": {
                                                                        "videoRenderer": {
                                                                            "videoId": video_id,
                                                                            "title": {"runs": [{"text": "A video"}]},
                                                                        }
                                                                    },
                                                                }
                                                            }
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ]
            }
        }
    }
    return f"<html><script>var ytInitialData = {json.dumps(initial_data)};</script></html>"


def test_collect_video_ids_finds_watch_endpoint():
    node = {"contentText": {"runs": [{"navigationEndpoint": {"watchEndpoint": {"videoId": "YfZ1b_PreUE"}}}]}}
    assert cli._collect_video_ids(node) == ["YfZ1b_PreUE"]


def test_collect_video_ids_ignores_non_video_ids():
    node = {"videoId": "not_a_real_id", "other": {"videoId": "YfZ1b_PreUE"}}
    assert cli._collect_video_ids(node) == ["YfZ1b_PreUE"]


def test_find_backstage_post():
    node = {"a": {"b": {"backstagePostRenderer": {"postId": "x"}}}}
    assert cli._find_backstage_post(node) == {"postId": "x"}


def test_extract_video_urls_from_post(monkeypatch):
    video_id = "YfZ1b_PreUE"

    class FakeResponse:
        text = _post_html_with_video(video_id)

        def raise_for_status(self):
            return None

    monkeypatch.setattr(cli.requests, "get", lambda *a, **k: FakeResponse())
    urls = cli._extract_youtube_video_urls_from_community_post(
        "https://www.youtube.com/post/Ugkx123"
    )
    assert urls == [f"https://www.youtube.com/watch?v={video_id}"]


def test_extract_video_urls_deduplicates(monkeypatch):
    video_id = "YfZ1b_PreUE"
    html = (
        _post_html_with_video(video_id)
        + f'<a href="https://www.youtube.com/watch?v={video_id}">link</a>'
    )

    class FakeResponse:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr(cli.requests, "get", lambda *a, **k: FakeResponse())
    urls = cli._extract_youtube_video_urls_from_community_post(
        "https://www.youtube.com/post/Ugkx123"
    )
    assert urls == [f"https://www.youtube.com/watch?v={video_id}"]
