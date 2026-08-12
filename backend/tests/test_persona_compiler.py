import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.persona_compiler import (
    PERSONA_MANDATORY_RULES_V1,
    PersonaCompiler,
    canonical_json_bytes,
    frame,
    legacy_yaml_to_persona_v1,
)
from app.services.prompt_renderer import default_prompt_renderer


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "persona_v1_bootstrap.json"


def _valid_config() -> dict[str, object]:
    return {
        "identity": {
            "name": " 林夕 ",
            "species": "原创虚拟角色",
            "role": "陪伴型文字对话伙伴",
        },
        "background": " 安静书房里的原创虚拟角色。 ",
        "personality": {
            "core_traits": [" 温和 ", "可靠"],
            "values": ["尊重边界", "准确"],
        },
        "language_style": {
            "tone": "自然、克制",
            "habits": ["简洁中文", "必要时列点"],
        },
        "relationship": {"initial": "刚刚认识。"},
        "additional_prohibitions": ["不得虚构共同经历。"],
    }


def _compiler(*, max_characters: int = 8_000) -> PersonaCompiler:
    renderer = default_prompt_renderer()
    return PersonaCompiler(
        template_text=renderer.load_template_text(),
        persona_max_characters=max_characters,
    )


def test_canonical_json_and_frame_are_deterministic() -> None:
    left = canonical_json_bytes({"b": "值", "a": 1})
    right = canonical_json_bytes({"a": 1, "b": "值"})

    assert left == right == '{"a":1,"b":"值"}'.encode()
    assert frame((b"a", b"bc")) == (
        (1).to_bytes(8, "big") + b"a" + (2).to_bytes(8, "big") + b"bc"
    )


def test_compiler_normalizes_outer_whitespace_without_unicode_folding() -> None:
    compiled = _compiler().compile(_valid_config())

    assert compiled.source_content["identity"]["name"] == "林夕"
    assert compiled.source_content["personality"]["core_traits"] == ["温和", "可靠"]

    variant = _valid_config()
    variant["identity"] = {
        **variant["identity"],
        "name": "林夕",
    }
    assert _compiler().compile(variant).source_content["identity"]["name"] == "林夕"


def test_behavior_fingerprint_binds_every_behavior_input() -> None:
    compiler = _compiler()
    valid_config = _valid_config()
    baseline = compiler.compile(valid_config)

    reversed_config = dict(reversed(list(valid_config.items())))
    assert compiler.compile(reversed_config) == baseline
    assert (
        replace(compiler, ruleset_version="persona-ruleset-v2")
        .compile(valid_config)
        .behavior_fingerprint
        != baseline.behavior_fingerprint
    )
    assert (
        replace(compiler, template_version="persona-template-v2")
        .compile(valid_config)
        .behavior_fingerprint
        != baseline.behavior_fingerprint
    )
    assert (
        replace(compiler, compiler_version="persona-compiler-v2")
        .compile(valid_config)
        .behavior_fingerprint
        != baseline.behavior_fingerprint
    )
    assert (
        replace(compiler, template_text=compiler.template_text + "\n固定规则")
        .compile(valid_config)
        .behavior_fingerprint
        != baseline.behavior_fingerprint
    )


def test_content_identity_hash_ignores_behavior_only_versions() -> None:
    compiler = _compiler()
    baseline = compiler.compile(_valid_config())
    changed = replace(compiler, ruleset_version="persona-ruleset-v2").compile(
        _valid_config()
    )

    assert changed.content_identity_hash == baseline.content_identity_hash
    assert changed.behavior_fingerprint != baseline.behavior_fingerprint


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "unexpected": "x"},
        lambda value: {**value, "identity": {**value["identity"], "extra": "x"}},
        lambda value: {**value, "background": " "},
        lambda value: {
            **value,
            "personality": {**value["personality"], "core_traits": ["温和", " 温和 "]},
        },
        lambda value: {**value, "additional_prohibitions": ["x"] * 21},
    ],
)
def test_compiler_rejects_invalid_schema(mutation) -> None:
    with pytest.raises(ValueError):
        _compiler().compile(mutation(_valid_config()))


def test_compiler_rejects_credentials_in_any_source_field() -> None:
    config = _valid_config()
    config["background"] = "api_key=sk-secretvalue123"

    with pytest.raises(ValueError, match="credential"):
        _compiler().compile(config)


def test_compiler_rejects_oversized_rendered_prompt() -> None:
    with pytest.raises(ValueError, match="Persona prompt exceeds"):
        _compiler(max_characters=10).compile(_valid_config())


def test_compiler_appends_mandatory_rules_before_configurable_rules() -> None:
    compiled = _compiler().compile(_valid_config())

    positions = [
        compiled.rendered_system_prompt.index(rule)
        for rule in PERSONA_MANDATORY_RULES_V1
    ]
    assert positions == sorted(positions)
    assert positions[-1] < compiled.rendered_system_prompt.index("不得虚构共同经历。")


def test_packaged_bootstrap_matches_frozen_fixture() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    renderer = default_prompt_renderer()
    compiled = _compiler().compile(renderer.load_persona_v1_config())

    assert compiled.source_content == fixture["normalized_config"]
    assert len(compiled.rendered_system_prompt) == fixture["rendered_prompt_length"]
    assert compiled.content_identity_hash == fixture["content_identity_hash"]
    assert compiled.behavior_fingerprint == fixture["behavior_fingerprint"]


def test_legacy_translation_requires_exact_keys() -> None:
    source = default_prompt_renderer().load_source_config()
    assert legacy_yaml_to_persona_v1(source)["additional_prohibitions"] == source[
        "prohibitions"
    ]

    with pytest.raises(ValueError, match="legacy Persona config keys"):
        legacy_yaml_to_persona_v1({**source, "unexpected": "x"})
