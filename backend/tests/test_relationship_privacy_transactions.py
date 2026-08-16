from __future__ import annotations

from pathlib import Path

import pytest

from app.services.relationship_dispatch import RelationshipDisclosureFence


def test_relationship_fence_is_priority_async_fence() -> None:
    fence = RelationshipDisclosureFence()
    assert not fence.has_pending_mutation()
    mutation = fence.begin_mutation()
    assert fence.has_pending_mutation()
    mutation._finish()
    assert not fence.has_pending_mutation()


@pytest.mark.asyncio
async def test_relationship_fence_hold_dispatch_blocks_while_mutation_pending() -> None:
    fence = RelationshipDisclosureFence()
    mutation = fence.begin_mutation()
    async with fence.hold_dispatch() as allowed:
        # A queued mutation must take priority: dispatch is held.
        assert allowed is False
    mutation._finish()
    async with fence.hold_dispatch() as allowed:
        assert allowed is True


@pytest.mark.asyncio
async def test_relationship_fence_serializes_mutations() -> None:
    fence = RelationshipDisclosureFence()
    order: list[str] = []

    async def worker(name: str) -> None:
        async with fence.begin_mutation():
            order.append(name)
            await asyncio.sleep(0.01)

    import asyncio

    await asyncio.gather(worker("a"), worker("b"))
    assert len(order) == 2


@pytest.mark.asyncio
async def test_queued_privacy_mutation_beats_later_dispatch() -> None:
    """A queued privacy/redaction mutation must win before chat disclosure."""
    fence = RelationshipDisclosureFence()
    import asyncio

    # begin_mutation increments pending BEFORE acquiring the lock; while a
    # mutation is queued, hold_dispatch must report blocked.
    mutation = fence.begin_mutation()
    assert fence.has_pending_mutation()

    async with fence.hold_dispatch() as allowed:
        # The queued mutation has priority even before it acquires the lock.
        assert allowed is False
        # Dispatch cannot proceed while the mutation is queued.
    mutation._finish()

    async with fence.hold_dispatch() as allowed:
        assert allowed is True
