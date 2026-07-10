from pathlib import Path
from typing import Any

import yaml


class PromptRenderer:
    def __init__(self, character_path: Path, template_path: Path) -> None:
        self._character_path = character_path
        self._template_path = template_path

    def render(self) -> str:
        config = self._load_character_config()
        template = self._template_path.read_text(encoding="utf-8")
        identity = config["identity"]
        personality = config["personality"]
        language_style = config["language_style"]
        relationship = config["relationship"]

        return template.format(
            name=identity["name"],
            species=identity["species"],
            role=identity["role"],
            background=config["background"],
            core_traits="、".join(personality["core_traits"]),
            values="、".join(personality["values"]),
            tone=language_style["tone"],
            habits="；".join(language_style["habits"]),
            initial_relationship=relationship["initial"],
            prohibitions="\n".join(f"- {item}" for item in config["prohibitions"]),
        )

    def _load_character_config(self) -> dict[str, Any]:
        raw = yaml.safe_load(self._character_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Character config must be a mapping")
        required = ["identity", "background", "personality", "language_style", "relationship", "prohibitions"]
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError(f"Character config missing keys: {', '.join(missing)}")
        return raw


def default_prompt_renderer() -> PromptRenderer:
    prompts_dir = Path(__file__).resolve().parents[1] / "prompts"
    return PromptRenderer(
        character_path=prompts_dir / "character.yaml",
        template_path=prompts_dir / "system_prompt.txt",
    )
