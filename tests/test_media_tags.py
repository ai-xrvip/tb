"""Tests for media_tags module."""
import pytest
from media_tags import (
    DEFAULT_MEDIA_TAGS, ROLE_MEDIA_TAGS, get_media_config,
    get_tags_for_role, get_folder, get_tier, get_max_tier_for_text,
    extract_media_tags, strip_media_tags, MEDIA_TAG_RE,
)

class TestMediaTags:
    def test_default_tags_count(self):
        assert len(DEFAULT_MEDIA_TAGS) >= 50

    def test_role_tag_overrides(self):
        assert "xiaolu" in ROLE_MEDIA_TAGS
        tags = get_tags_for_role("xiaolu")
        assert "日常" in tags
        assert "Cos" in tags

    def test_get_folder_returns_string(self):
        folder = get_folder("xiaolu", "日常")
        assert isinstance(folder, str)

    def test_get_tier_default_zero(self):
        assert get_tier("xiaolu", "nonexistent_tag") == 0

    def test_get_tier_for_known_tag(self):
        assert get_tier("xiaolu", "全裸") == 3

    def test_get_max_tier_for_text(self):
        text = "快来我房间看看[media:全裸]"
        assert get_max_tier_for_text("xiaolu", text) >= 3

    def test_extract_media_tags(self):
        text = "看这张[media:Cos]还有这张[media:日常]"
        tags = extract_media_tags(text)
        assert "Cos" in tags
        assert "日常" in tags

    def test_strip_media_tags(self):
        text = "好看吗[media:Cos]还有这个[media:日常]"
        cleaned = strip_media_tags(text)
        assert "[media:" not in cleaned
        assert "好看吗" in cleaned

    def test_media_tag_regex(self):
        assert MEDIA_TAG_RE.match("[media:测试]")
        assert not MEDIA_TAG_RE.match("plain text")

    def test_get_media_config_nonexistent(self):
        assert get_media_config("xiaolu", "不存在的标签") is None
