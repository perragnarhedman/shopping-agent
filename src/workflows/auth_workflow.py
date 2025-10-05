from __future__ import annotations

from typing import Any, Dict

from temporalio import workflow

from .activities import run_authentication_activity


@workflow.defn(name="authentication_v1")
class AuthenticationWorkflow:
    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = await workflow.execute_activity(
            run_authentication_activity,
            payload,
            start_to_close_timeout=workflow.timedelta(seconds=900),
        )
        return result


