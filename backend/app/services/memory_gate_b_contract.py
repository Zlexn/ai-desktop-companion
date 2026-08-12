from app.domain.models import MemoryType


MEMORY_WRITE_PURPOSE = (
    "write Governor-approved durable memories to local active storage"
)
MEMORY_AUTO_ACTIVE_SCHEMA_VERSION = "memory-auto-active-schema-v1"
MEMORY_WRITE_POLICY_VERSION = "memory-auto-write-policy-v1"
MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION = "memory-auto-write-retention-v1"
MEMORY_CANONICALIZATION_VERSION = "memory-canonicalization-v1"
MEMORY_COMMIT_POLICY_VERSION = "memory-commit-policy-v1"
MEMORY_SOURCE_REFERENCE_VERSION = "memory-source-reference-v1"
MEMORY_ALLOWED_AUTO_TYPES_VERSION = "memory-auto-write-types-v1"
MEMORY_GATE_B_FIXTURE_SCHEMA_VERSION = "memory-gate-b-fixtures-v1"

MEMORY_ALLOWED_AUTO_TYPES = (
    MemoryType.USER_FACT,
    MemoryType.PREFERENCE,
    MemoryType.LONG_TERM_GOAL,
    MemoryType.IMPORTANT_EVENT,
    MemoryType.RELATIONSHIP_EVENT,
    MemoryType.OTHER,
)

MEMORY_COMMIT_SEMANTIC_RETRIES_DEFAULT = 2
MEMORY_COMMIT_SEMANTIC_RETRIES_MAX = 3
