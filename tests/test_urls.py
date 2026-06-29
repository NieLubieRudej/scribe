"""URL classification is pure and must be rock-solid — it decides the whole flow."""

from scribe import urls


def test_watch_is_video():
    c = urls.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert c.kind == urls.VIDEO and c.video_id == "dQw4w9WgXcQ"


def test_youtu_be_short_link():
    c = urls.classify("https://youtu.be/dQw4w9WgXcQ")
    assert c.kind == urls.VIDEO and c.video_id == "dQw4w9WgXcQ"


def test_shorts_is_video_canonicalized():
    c = urls.classify("https://www.youtube.com/shorts/abcdefghijk")
    assert c.kind == urls.VIDEO and c.video_id == "abcdefghijk"
    assert "watch?v=abcdefghijk" in c.url


def test_watch_with_list_prefers_video():
    c = urls.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123")
    assert c.kind == urls.VIDEO and c.video_id == "dQw4w9WgXcQ"


def test_playlist_is_collection():
    c = urls.classify("https://www.youtube.com/playlist?list=PLabc")
    assert c.kind == urls.COLLECTION


def test_bare_handle_pins_videos_tab():
    c = urls.classify("@veritasium")
    assert c.kind == urls.COLLECTION and c.url.endswith("/@veritasium/videos")


def test_handle_url_pins_videos_tab():
    c = urls.classify("https://www.youtube.com/@veritasium")
    assert c.url.endswith("/@veritasium/videos")


def test_explicit_streams_tab_is_kept():
    c = urls.classify("https://www.youtube.com/@veritasium/streams")
    assert c.kind == urls.COLLECTION and c.url.endswith("/streams")


def test_non_video_tab_falls_back_to_videos():
    c = urls.classify("https://www.youtube.com/channel/UCabc123/featured")
    assert c.url.endswith("/channel/UCabc123/videos")


def test_c_and_user_paths():
    assert urls.classify("https://www.youtube.com/c/Veritasium").url.endswith("/c/Veritasium/videos")
    assert urls.classify("https://www.youtube.com/user/1veritasium").url.endswith("/user/1veritasium/videos")


def test_garbage_is_unknown():
    assert urls.classify("garbage string").kind == urls.UNKNOWN
    assert urls.classify("").kind == urls.UNKNOWN


def test_videoseries_is_collection_not_a_video():
    assert urls.classify("https://www.youtube.com/embed/videoseries?list=PLabc").kind == urls.COLLECTION
    assert urls.classify("https://www.youtube.com/watch?v=videoseries&list=PLabc").kind == urls.COLLECTION


def test_spoofed_host_rejected_real_subdomain_accepted():
    assert urls.classify("https://notyoutube.com/watch?v=dQw4w9WgXcQ").kind == urls.UNKNOWN
    assert urls.classify("https://music.youtube.com/watch?v=dQw4w9WgXcQ").kind == urls.VIDEO
