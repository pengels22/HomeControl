"""Bounded in-process HCM event subscriptions using the existing EventRecord model.

Best-effort delivery, not a durable automation queue. Slow consumers lose their
oldest queued event and can inspect dropped counts; they never block producers.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from importlib import import_module

EventRecord = import_module('07_servises.common.module_infra').EventRecord


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue
    dropped: int = 0


class EventBus:
    def __init__(self, capacity=128):
        if capacity < 1:
            raise ValueError('Event queue capacity must be positive')
        self.capacity = capacity
        self._subscriptions = set()

    @contextmanager
    def subscribe(self):
        subscription = Subscription(asyncio.Queue(maxsize=self.capacity))
        self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            self._subscriptions.discard(subscription)

    def publish(self, event: EventRecord):
        for subscription in self._subscriptions:
            if subscription.queue.full():
                subscription.queue.get_nowait()
                subscription.queue.task_done()
                subscription.dropped += 1
            subscription.queue.put_nowait(deepcopy(event))


event_bus = EventBus()
