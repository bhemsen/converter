"""Tests for the leaf module and the two profiles it declares."""

import ast
import dataclasses
import inspect

import pytest

from converter import profiles
from converter.profiles import MP4, WAV, Attempt, Profile, StreamRule, flags


class TestLeafModule:
    def test_imports_nothing_from_converter(self):
        """The leaf property is checked, not trusted: parse the actual import
        statements (not the prose that happens to mention them) and assert none
        names ``converter``."""
        tree = ast.parse(inspect.getsource(profiles))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)

        assert not any(
            name == "converter" or name.startswith("converter.") for name in imported_modules
        )


class TestFlags:
    def test_splits_a_command_line_shaped_string(self):
        assert flags("-c:v copy -c:a aac") == ("-c:v", "copy", "-c:a", "aac")

    def test_empty_spec_is_the_empty_tuple(self):
        assert flags("") == ()


class TestMp4Profile:
    def test_label_and_suffix(self):
        assert MP4.label == "MP4"
        assert MP4.target_suffix == ".mp4"

    def test_container_options_carry_faststart_once(self):
        assert MP4.container_options == ("-movflags", "+faststart")

    def test_cheap_attempt_excludes_container_options(self):
        """The engine appends container options once; the declared attempt must
        not repeat them (Prior decisions, spec-profile-registry)."""
        assert MP4.cheap_attempt.label == "remux"
        assert "-movflags" not in MP4.cheap_attempt.options
        assert "+faststart" not in MP4.cheap_attempt.options

    def test_cheap_attempt_selects_streams_blindly(self):
        assert MP4.explicit_streams is False

    def test_last_resort_excludes_container_options_too(self):
        assert MP4.last_resort is not None
        assert MP4.last_resort.label == "re-encode"
        assert "-movflags" not in MP4.last_resort.options

    def test_has_exactly_the_three_stream_rules(self):
        assert set(MP4.rules) == {"video", "audio", "subtitle"}

    def test_video_and_audio_rules_carry_the_position_placeholder(self):
        for stream_type in ("video", "audio"):
            rule = MP4.rules[stream_type]
            assert "{n}" in " ".join(rule.accept_options)
            assert rule.fallback_options is not None
            assert "{n}" in " ".join(rule.fallback_options)

    def test_subtitle_rule_transcodes_to_mov_text_and_has_no_fallback(self):
        rule = MP4.rules["subtitle"]

        assert rule.accept_options == ("-c:s:{n}", "mov_text")
        assert rule.fallback_options is None
        assert rule.drop_reason == "bitmap subtitles cannot be stored in MP4"


class TestWavProfile:
    def test_label_and_suffix(self):
        assert WAV.label == "WAV"
        assert WAV.target_suffix == ".wav"

    def test_no_container_options(self):
        assert WAV.container_options == ()

    def test_cheap_attempt_selects_streams_explicitly(self):
        assert WAV.explicit_streams is True
        assert WAV.cheap_attempt.options == ("-map", "0:a:0", "-c:a", "pcm_s16le")

    def test_declares_no_last_resort(self):
        assert WAV.last_resort is None

    def test_declares_only_an_audio_rule(self):
        assert set(WAV.rules) == {"audio"}

    def test_audio_rule_has_an_empty_copy_mask(self):
        assert WAV.rules["audio"].copy_mask == frozenset()

    def test_audio_rule_fallback_is_placeholder_free(self):
        rule = WAV.rules["audio"]

        assert rule.fallback_options == ("-c:a", "pcm_s16le")
        assert "{n}" not in " ".join(rule.fallback_options)
        assert "{n}" not in " ".join(rule.accept_options)

    def test_audio_rule_fallback_carries_no_re_encode_note(self):
        """Decoding to PCM is the point of WAV, not a loss."""
        assert WAV.rules["audio"].fallback_name is None

    def test_audio_rule_stream_limit_is_one(self):
        assert WAV.rules["audio"].stream_limit == 1


class TestValueTypesAreFrozen:
    def test_attempt_is_frozen(self):
        attempt = Attempt(label="x", options=())

        with pytest.raises(AttributeError):
            attempt.label = "y"

    def test_stream_rule_is_frozen(self):
        rule = StreamRule(copy_mask=frozenset(), accept_options=())

        with pytest.raises(AttributeError):
            rule.copy_mask = frozenset({"x"})

    def test_profile_is_frozen(self):
        with pytest.raises(AttributeError):
            MP4.label = "changed"

    def test_profile_dataclass_shape(self):
        """Sanity check the type itself, not just the two instances."""
        fields = {f.name for f in dataclasses.fields(Profile)}

        assert fields == {
            "label",
            "target_suffix",
            "container_options",
            "cheap_attempt",
            "explicit_streams",
            "rules",
            "last_resort",
        }
