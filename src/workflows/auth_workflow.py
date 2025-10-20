from __future__ import annotations

from typing import Any, Dict
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from .activities import run_authentication_activity


@workflow.defn(name="authentication_v1")
class AuthenticationWorkflow:
    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Retry policy: max 2 retries, exponential backoff
        retry_policy = RetryPolicy(
            maximum_attempts=2,
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=10),
            backoff_coefficient=2.0
        )
        
        result = await workflow.execute_activity(
            run_authentication_activity,
            payload,
            start_to_close_timeout=workflow.timedelta(seconds=900),
            retry_policy=retry_policy
        )
        return result


