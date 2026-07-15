import asyncio

import pytest

from app.services.emotion_analysis_scheduler import InProcessEmotionAnalysisScheduler


@pytest.mark.asyncio
async def test_scheduler_runs_each_assistant_id_at_most_once_while_active() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def job(user_message_id: str, assistant_message_id: str, base_emotion_version: int) -> None:
        calls.append((user_message_id, assistant_message_id, base_emotion_version))
        started.set()
        await release.wait()

    scheduler = InProcessEmotionAnalysisScheduler(job)
    scheduler.schedule("user-1", "assistant-1", 7)
    scheduler.schedule("user-1", "assistant-1", 7)
    await started.wait()
    release.set()
    await scheduler.shutdown()

    assert calls == [("user-1", "assistant-1", 7)]


@pytest.mark.asyncio
async def test_scheduler_failure_is_isolated_and_shutdown_completes() -> None:
    completed = asyncio.Event()

    async def job(_user_message_id: str, _assistant_message_id: str, _base_emotion_version: int) -> None:
        completed.set()
        raise RuntimeError("analysis failure")

    scheduler = InProcessEmotionAnalysisScheduler(job)
    scheduler.schedule("user-1", "assistant-1", 7)
    await completed.wait()
    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_scheduler_ignores_new_work_after_shutdown() -> None:
    calls = []

    async def job(user_message_id: str, assistant_message_id: str, base_emotion_version: int) -> None:
        calls.append((user_message_id, assistant_message_id, base_emotion_version))

    scheduler = InProcessEmotionAnalysisScheduler(job)
    await scheduler.shutdown()
    scheduler.schedule("user-1", "assistant-1", 7)
    await asyncio.sleep(0)

    assert calls == []
