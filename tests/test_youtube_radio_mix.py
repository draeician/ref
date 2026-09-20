"""Tests for YouTube radio/mix URL detection (list=RD... / start_radio=1)."""

from urllib.parse import parse_qs

from ref_cli import cli


def test_start_radio_marks_radio_mix():
    qs = parse_qs("v=YfZ1b_PreUE&list=RDYfZ1b_PreUE&start_radio=1")
    assert cli._is_youtube_radio_mix(qs) is True


def test_rd_list_without_start_radio_is_radio_mix():
    qs = parse_qs("v=YfZ1b_PreUE&list=RDYfZ1b_PreUE")
    assert cli._is_youtube_radio_mix(qs) is True


def test_real_playlist_is_not_radio_mix():
    qs = parse_qs("v=YfZ1b_PreUE&list=PLABC123def")
    assert cli._is_youtube_radio_mix(qs) is False


def test_single_video_is_not_radio_mix():
    qs = parse_qs("v=YfZ1b_PreUE")
    assert cli._is_youtube_radio_mix(qs) is False


def test_no_list_param_is_not_radio_mix():
    qs = parse_qs("t=30")
    assert cli._is_youtube_radio_mix(qs) is False


def test_community_post_url_is_detected():
    url = "https://www.youtube.com/post/UgkxGyRu959b87V-_rlu_E4vABcggpj4__M6"
    assert cli._is_youtube_community_post(url) is True


def test_watch_url_is_not_community_post():
    url = "https://www.youtube.com/watch?v=YfZ1b_PreUE"
    assert cli._is_youtube_community_post(url) is False


def test_playlist_url_is_not_community_post():
    url = "https://www.youtube.com/playlist?list=PLABC123def"
    assert cli._is_youtube_community_post(url) is False
