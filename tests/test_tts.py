"""Tests for TTS module."""
from providers.tts import (
    ROLE_VOICE_MAP, get_voice_for_role,
    MOOD_SSML, _clean_tts_text, _build_ssml,
)

class TestTTSModule:
    def test_all_roles_have_voices(self):
        """All 30 roles should have a voice assigned."""
        assert len(ROLE_VOICE_MAP) >= 30

    def test_get_voice_returns_string(self):
        voice = get_voice_for_role("xiaolu")
        assert isinstance(voice, str)
        assert voice.startswith("zh-CN-")

    def test_get_voice_fallback(self):
        voice = get_voice_for_role("nonexistent_role")
        assert voice == "zh-CN-XiaochenNeural"

    def test_all_moods_have_config(self):
        required = ["happy", "tired", "sleepy", "sad", "playful", "sexy", "angry", "neutral", "period"]
        for mood in required:
            assert mood in MOOD_SSML, f"Missing mood: {mood}"
            cfg = MOOD_SSML[mood]
            assert "style" in cfg
            assert "rate" in cfg
            assert "pitch" in cfg

    def test_clean_tts_removes_emoji(self):
        result = _clean_tts_text("你好😊今天开心🥰")
        assert "😊" not in result
        assert "🥰" not in result
        assert "你好" in result
        assert "今天开心" in result

    def test_clean_tts_removes_brackets(self):
        result = _clean_tts_text("看这里[media:Cos]怎么样")
        assert "[media:" not in result

    def test_clean_tts_removes_kaomoji(self):
        result = _clean_tts_text("好呀(ノω<。)怎么样")
        assert "ノω" not in result

    def test_build_ssml_contains_voice(self):
        ssml = _build_ssml("你好", "zh-CN-XiaoxiaoNeural", "happy")
        assert "zh-CN-XiaoxiaoNeural" in ssml
        assert "cheerful" in ssml
        assert "+15%" in ssml

    def test_build_ssml_adds_breaks(self):
        ssml = _build_ssml("你好。再见！", "zh-CN-XiaoxiaoNeural")
        assert 'break time="300ms"' in ssml
