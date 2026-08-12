from __future__ import annotations


MEMORY_ELIGIBLE_PREDICATE = """
memory.status = 'active'
AND (
    (
        state.memory_id IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM memory_conflicts AS eligible_legacy_conflict
            WHERE eligible_legacy_conflict.status = 'open'
              AND memory.id IN (
                  eligible_legacy_conflict.left_memory_id,
                  eligible_legacy_conflict.right_memory_id
              )
        )
    )
    OR (
        state.state = 'active'
        AND state.current_version_id IS NOT NULL
        AND state.head_version > 0
        AND version.id IS NOT NULL
        AND version.operation <> 'delete'
        AND version.content IS NOT NULL
        AND version.redacted_at IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM memory_conflicts AS eligible_current_conflict
            WHERE eligible_current_conflict.status = 'open'
              AND memory.id IN (
                  eligible_current_conflict.left_memory_id,
                  eligible_current_conflict.right_memory_id
              )
        )
    )
)
"""
