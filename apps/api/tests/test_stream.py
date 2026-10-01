import asyncio
from collections.abc import AsyncIterator

from careergraph.agent.events import AgentEvent, TextDelta
from careergraph.api.routes.chat import with_heartbeat


async def _slow(delays: list[float]) -> AsyncIterator[AgentEvent]:
    for i, delay in enumerate(delays):
        await asyncio.sleep(delay)
        yield TextDelta(str(i))


async def test_heartbeat_fills_silences_and_keeps_order() -> None:
    items = [item async for item in with_heartbeat(_slow([0.0, 0.25, 0.0]), interval=0.05)]
    events = [item for item in items if item is not None]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["0", "1", "2"]
    assert items.count(None) >= 3  # the 0.25 s gap was filled with keep-alives


async def test_closing_the_stream_cancels_the_pending_step() -> None:
    cancelled = asyncio.Event()

    async def stuck() -> AsyncIterator[AgentEvent]:
        yield TextDelta("first")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        yield TextDelta("never")

    stream = with_heartbeat(stuck(), interval=0.02)
    assert isinstance(await anext(stream), TextDelta)
    assert await anext(stream) is None  # heartbeat while the agent is stuck
    await stream.aclose()  # e.g. the client disconnected
    assert cancelled.is_set()
