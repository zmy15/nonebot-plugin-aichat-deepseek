import asyncio


async def test_aggregates_consecutive_messages(aggregator_mod) -> None:
    completed = []

    async def is_complete(key, text, images) -> bool:
        return True

    async def handle(key, text, images, send) -> None:
        completed.append((key, text, images))

    async def send(message: str) -> None:
        pass

    aggregator = aggregator_mod.MessageAggregator(
        debounce_seconds=0.02,
        debounce_jitter=0,
        is_complete=is_complete,
        handler=handle,
    )

    await aggregator.add("1:2", "你", [], send)
    await aggregator.add("1:2", "好", [], send)
    await asyncio.sleep(0.1)

    assert completed == [("1:2", "你\n好", [])]


async def test_incomplete_message_waits_for_more(aggregator_mod) -> None:
    completed = []
    decisions = iter([False, True])

    async def is_complete(key, text, images) -> bool:
        return next(decisions)

    async def handle(key, text, images, send) -> None:
        completed.append(text)

    async def send(message: str) -> None:
        pass

    aggregator = aggregator_mod.MessageAggregator(
        debounce_seconds=0.02,
        debounce_jitter=0,
        is_complete=is_complete,
        handler=handle,
    )

    await aggregator.add("1:2", "我想问", [], send)
    await asyncio.sleep(0.08)
    assert completed == []

    await aggregator.add("1:2", "天气怎么样", [], send)
    await asyncio.sleep(0.1)
    assert completed == ["我想问\n天气怎么样"]


async def test_images_are_kept_in_batch(aggregator_mod) -> None:
    completed = []

    async def is_complete(key, text, images) -> bool:
        return True

    async def handle(key, text, images, send) -> None:
        completed.append((text, images))

    async def send(message: str) -> None:
        pass

    aggregator = aggregator_mod.MessageAggregator(
        debounce_seconds=0.02,
        debounce_jitter=0,
        is_complete=is_complete,
        handler=handle,
    )

    await aggregator.add("1:2", "", [{"url": "a.png"}], send)
    await aggregator.add("1:2", "这是什么", [{"url": "b.png"}], send)
    await asyncio.sleep(0.1)

    assert completed == [
        ("这是什么", [{"url": "a.png"}, {"url": "b.png"}])
    ]


async def test_discard_drops_pending_messages(aggregator_mod) -> None:
    completed = []

    async def is_complete(key, text, images) -> bool:
        return True

    async def handle(key, text, images, send) -> None:
        completed.append(text)

    async def send(message: str) -> None:
        pass

    aggregator = aggregator_mod.MessageAggregator(
        debounce_seconds=0.02,
        debounce_jitter=0,
        is_complete=is_complete,
        handler=handle,
    )

    await aggregator.add("1:2", "还没发完", [], send)
    await aggregator.discard("1:2")
    await asyncio.sleep(0.1)

    assert completed == []
