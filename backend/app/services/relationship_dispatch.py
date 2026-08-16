from __future__ import annotations

from app.services.summary_dispatch import PriorityAsyncFence


class RelationshipDisclosureFence(PriorityAsyncFence):
    """Serializes relationship privacy/redaction against queued chat disclosure.

    Lock order everywhere:
        SummaryProcessingFence -> RelationshipDisclosureFence -> SummaryDisclosureFence

    Memory forget and session deletion routes acquire relationship before summary
    disclosure. Relationship-only mutations acquire only relationship disclosure.
    No code acquires these in reverse order.
    """
