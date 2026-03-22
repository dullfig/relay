from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import heapq


@dataclass(order=True)
class Event:
    time: float
    seq: int
    description: str = field(compare=False)
    action: Callable[[], None] = field(compare=False)


class EventQueue:
    """Priority queue of simulation events, ordered by time."""

    def __init__(self):
        self._heap: list[Event] = []
        self._seq = 0

    def schedule(self, time: float, description: str, action: Callable[[], None]):
        event = Event(time=time, seq=self._seq, description=description, action=action)
        self._seq += 1
        heapq.heappush(self._heap, event)

    def pop(self) -> Event | None:
        if self._heap:
            return heapq.heappop(self._heap)
        return None

    def peek_time(self) -> float | None:
        if self._heap:
            return self._heap[0].time
        return None

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)
