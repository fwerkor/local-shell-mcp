"""Python LangGraph saver adapter over the existing owner-scoped SQLite tuples.

The optional dependency is imported by the WebUI graph path, never by Worker.
LangGraph 1.0 checkpoints contain `Send` and other non-JSON types: store every
channel and write via the SDK serializer rather than lossy JSON conversion.
"""
from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple

from .checkpoints import SQLiteCheckpointSaver


class OwnedGraphCheckpointer(BaseCheckpointSaver):
    def __init__(self, database: Any, owner: str):
        super().__init__()
        self.storage = SQLiteCheckpointSaver(database, owner)

    def _encode(self, value: Any) -> dict:
        kind, data = self.serde.dumps_typed(value)
        return {"type": kind, "data": base64.b64encode(data).decode("ascii")}

    def _decode(self, value: dict) -> Any:
        return self.serde.loads_typed((value["type"], base64.b64decode(value["data"])))

    def _tuple(self, row: dict | None) -> CheckpointTuple | None:
        if row is None:
            return None
        return CheckpointTuple(
            row["config"], self._decode(row["checkpoint"]["typed"]),
            self._decode(row["metadata"]["typed"]), row.get("parentConfig"),
            [(task, channel, self._decode(value)) for task, channel, value in row["pendingWrites"]],
        )

    def get_tuple(self, config: dict) -> CheckpointTuple | None:
        return self._tuple(self.storage.get_tuple(config))

    def list(self, config: dict | None, *, filter: dict | None = None,
             before: dict | None = None, limit: int | None = None) -> Iterator[CheckpointTuple]:
        if config is None:
            raise ValueError("Owner-scoped checkpoint enumeration requires a thread config")
        for row in self.storage.list(config, filter=filter, before=before, limit=limit):
            result = self._tuple(row)
            if result is not None:
                yield result

    def put(self, config: dict, checkpoint: dict, metadata: dict,
            new_versions: dict) -> dict:
        return self.storage.put(config, {"id": checkpoint["id"], "typed": self._encode(checkpoint)},
                                {"typed": self._encode(metadata)})

    def put_writes(self, config: dict, writes: list[tuple[str, Any]],
                   task_id: str, task_path: str = "") -> None:
        self.storage.put_writes(config, [(channel, self._encode(value)) for channel, value in writes],
                                task_id=task_id)

    async def aget_tuple(self, config: dict) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(self, config: dict | None, *, filter: dict | None = None,
                    before: dict | None = None, limit: int | None = None) -> AsyncIterator[CheckpointTuple]:
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(self, config: dict, checkpoint: dict, metadata: dict,
                   new_versions: dict) -> dict:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: dict, writes: list[tuple[str, Any]],
                          task_id: str, task_path: str = "") -> None:
        self.put_writes(config, writes, task_id, task_path)
