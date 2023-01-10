# helps manage tasks with the queue system in SuperText
from dataclasses import dataclass, field
import queue
from typing import Any


class TaskManager:
    @dataclass(order=True)
    class PrioritizedItem:
        priority: int
        item: Any=field(compare=False)
        descr: str=field(compare=False)
    def __init__(self):
        # a queue to balance different types of actions
        # has priorities, which is useful for making sure tasks occur in an expected order
        # 0 = highest priority
        self.actionQueue = queue.PriorityQueue()