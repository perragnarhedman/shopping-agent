from __future__ import annotations

from typing import Any, Dict

from temporalio import workflow

from .activities import run_shopping_activity


@workflow.defn(name="shopping_v1")
class ShoppingWorkflow:
    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = await workflow.execute_activity(
            run_shopping_activity,
            payload,
            start_to_close_timeout=workflow.timedelta(seconds=1800),
        )
        return result


