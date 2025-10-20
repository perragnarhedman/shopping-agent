from __future__ import annotations

import asyncio
import os
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from src.core.logger import setup_logging
from .activities import run_authentication_activity, run_shopping_activity, run_conversation_activity
from .auth_workflow import AuthenticationWorkflow
from .shopping_workflow import ShoppingWorkflow
from .conversation_workflow import ConversationWorkflow


async def main() -> None:
    setup_logging()
    logging.getLogger(__name__).info("Starting Temporal worker…")

    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")

    client = await Client.connect(address, namespace=namespace)

    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "shopping-agent-task-queue")

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[AuthenticationWorkflow, ShoppingWorkflow, ConversationWorkflow],
        activities=[run_authentication_activity, run_shopping_activity, run_conversation_activity],
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())


