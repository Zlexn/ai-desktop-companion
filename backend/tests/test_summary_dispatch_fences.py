from __future__ import annotations

import asyncio

import pytest

from app.services.summary_dispatch import (
    SummaryDisclosureFence,
    SummaryProcessingFence,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("fence_type", [SummaryProcessingFence, SummaryDisclosureFence])
async def test_queued_mutation_wins_before_dispatch(fence_type) -> None:
    fence = fence_type()
    dispatch_entered = asyncio.Event()
    release_dispatch = asyncio.Event()
    mutation_entered = asyncio.Event()
    second_dispatch_result: list[bool] = []

    async def first_dispatch() -> None:
        async with fence.hold_dispatch() as allowed:
            assert allowed is True
            dispatch_entered.set()
            await release_dispatch.wait()

    async def mutation() -> None:
        async with fence.begin_mutation():
            mutation_entered.set()

    async def second_dispatch() -> None:
        async with fence.hold_dispatch() as allowed:
            second_dispatch_result.append(allowed)

    first = asyncio.create_task(first_dispatch())
    await dispatch_entered.wait()
    queued_mutation = asyncio.create_task(mutation())
    await asyncio.sleep(0)
    assert fence.has_pending_mutation() is True
    second = asyncio.create_task(second_dispatch())

    release_dispatch.set()
    await mutation_entered.wait()
    await asyncio.gather(first, queued_mutation, second)

    assert second_dispatch_result == [False]
    assert fence.has_pending_mutation() is False


@pytest.mark.asyncio
async def test_processing_and_disclosure_fences_are_independent() -> None:
    processing = SummaryProcessingFence()
    disclosure = SummaryDisclosureFence()

    async with processing.begin_mutation():
        assert processing.has_pending_mutation() is True
        assert disclosure.has_pending_mutation() is False
        async with disclosure.hold_dispatch() as disclosure_allowed:
            assert disclosure_allowed is True

    async with disclosure.begin_mutation():
        assert disclosure.has_pending_mutation() is True
        assert processing.has_pending_mutation() is False
        async with processing.hold_dispatch() as processing_allowed:
            assert processing_allowed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("fence_type", [SummaryProcessingFence, SummaryDisclosureFence])
async def test_cancelled_waiting_mutation_releases_pending_count(fence_type) -> None:
    fence = fence_type()
    dispatch_entered = asyncio.Event()
    release_dispatch = asyncio.Event()

    async def dispatch() -> None:
        async with fence.hold_dispatch():
            dispatch_entered.set()
            await release_dispatch.wait()

    holder = asyncio.create_task(dispatch())
    await dispatch_entered.wait()
    waiting = asyncio.create_task(_enter_mutation(fence))
    await asyncio.sleep(0)
    assert fence.has_pending_mutation() is True

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert fence.has_pending_mutation() is False

    release_dispatch.set()
    await holder


async def _enter_mutation(fence) -> None:
    async with fence.begin_mutation():
        pass
