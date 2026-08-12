from dataclasses import dataclass


PERSONA_SCHEMA_VERSION = "persona-schema-v1"
PERSONA_RULESET_VERSION = "persona-ruleset-v1"
PERSONA_TEMPLATE_VERSION = "persona-template-v1"
PERSONA_COMPILER_VERSION = "persona-compiler-v1"
PERSONA_CANONICALIZATION_VERSION = "persona-canonical-json-v1"
CONTEXT_COMPOSER_VERSION = "context-composer-v2"
CONTEXT_DATA_ENCODER_VERSION = "context-data-json-v2"
CONTEXT_MANIFEST_VERSION = "context-manifest-v2"


@dataclass(frozen=True)
class ContextTypeBudget:
    max_items: int
    max_characters: int
    soft_min_items: int
