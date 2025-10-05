from __future__ import annotations

import os
from typing import Any, Dict

from temporalio.client import Client


async def get_temporal_client() -> Client:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    return await Client.connect(address, namespace=namespace)


async def start_workflow(client: Client, workflow: str, task_queue: str, payload: Dict[str, Any]) -> str:
    handle = await client.start_workflow(
        workflow,
        payload,
        id=payload.get("workflow_id") or None,
        task_queue=task_queue,
    )
    return handle.id


