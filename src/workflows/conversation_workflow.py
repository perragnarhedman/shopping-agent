from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from .activities import (
    run_conversation_activity,
    run_authentication_activity,
    run_shopping_activity
)


@dataclass
class ConversationState:
    """Persistent workflow state"""
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    session_context: Dict[str, Any] = field(default_factory=lambda: {
        "cart_items": [],
        "auth_status": "logged_out",
        "checkout_progress": None
    })
    clarification_count: int = 0
    agent_retry_count: Dict[str, int] = field(default_factory=dict)


@workflow.defn(name="conversation_v1")
class ConversationWorkflow:
    def __init__(self):
        self.state = ConversationState()
        # Retry policy: max 2 retries, exponential backoff
        self.retry_policy = RetryPolicy(
            maximum_attempts=2,
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=10),
            backoff_coefficient=2.0
        )
    
    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        user_message = payload["user_message"]
        
        # Add user message to history
        self.state.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        # Truncate history to last 50 messages
        if len(self.state.conversation_history) > 50:
            self.state.conversation_history = self.state.conversation_history[-50:]
        
        # Run ConversationAgent
        decision = await workflow.execute_activity(
            run_conversation_activity,
            {
                "user_message": user_message,
                "conversation_history": self.state.conversation_history[:-1],  # Exclude current message
                "session_context": self.state.session_context,
                "clarification_count": self.state.clarification_count
            },
            start_to_close_timeout=workflow.timedelta(seconds=30),
            retry_policy=self.retry_policy
        )
        
        # Update clarification count
        if decision["next_action"] == "await_user_input" and decision["clarification_questions"]:
            self.state.clarification_count += 1
        else:
            self.state.clarification_count = 0  # Reset on progress
        
        # Handle escalation
        if decision.get("needs_human_escalation"):
            response_message = decision["conversation_response"]
            self.state.conversation_history.append({
                "role": "assistant",
                "content": response_message
            })
            return {
                "message": response_message,
                "session_context": self.state.session_context,
                "next_action": "human_escalation_needed"
            }
        
        # Handle agent delegation
        if decision["next_action"] == "delegate_to_agent":
            agent_result = await self._delegate_with_retry(decision)
            
            # Update session context based on agent results
            self._update_session_context(agent_result, decision["agent_delegation"]["agent_type"])
            
            # Generate follow-up response
            follow_up_decision = await workflow.execute_activity(
                run_conversation_activity,
                {
                    "user_message": f"[AGENT_COMPLETED] {agent_result.get('result', {}).get('status', 'completed')}",
                    "conversation_history": self.state.conversation_history,
                    "session_context": self.state.session_context,
                    "clarification_count": 0
                },
                start_to_close_timeout=workflow.timedelta(seconds=30),
                retry_policy=self.retry_policy
            )
            response_message = follow_up_decision["conversation_response"]
        else:
            response_message = decision["conversation_response"]
        
        # Add assistant response to history
        self.state.conversation_history.append({
            "role": "assistant",
            "content": response_message
        })
        
        return {
            "message": response_message,
            "session_context": self.state.session_context,
            "next_action": decision["next_action"]
        }
    
    async def _delegate_with_retry(self, decision: Dict) -> Dict:
        """Delegate to specialized agent with 1 retry on failure"""
        agent_type = decision["agent_delegation"]["agent_type"]
        task_payload = decision["agent_delegation"]["task_payload"]
        
        # Track retries
        retry_key = agent_type
        current_retries = self.state.agent_retry_count.get(retry_key, 0)
        
        try:
            if agent_type == "authentication":
                result = await workflow.execute_activity(
                    run_authentication_activity,
                    task_payload,
                    start_to_close_timeout=workflow.timedelta(seconds=1800),
                    retry_policy=self.retry_policy
                )
            elif agent_type == "shopping":
                result = await workflow.execute_activity(
                    run_shopping_activity,
                    {**task_payload, "workflow_id": workflow.info().workflow_id, "store": "coop_se", "headless": False, "debug": True},
                    start_to_close_timeout=workflow.timedelta(seconds=1800),
                    retry_policy=self.retry_policy
                )
            else:
                result = {"ok": False, "error": f"Unknown agent type: {agent_type}"}
            
            # Success - reset retry count
            self.state.agent_retry_count[retry_key] = 0
            return result
        
        except Exception as e:
            # Failure - check retry count
            if current_retries < 1:  # Allow 1 retry
                self.state.agent_retry_count[retry_key] = current_retries + 1
                # Retry
                return await self._delegate_with_retry(decision)
            else:
                # Max retries reached
                self.state.agent_retry_count[retry_key] = 0
                return {
                    "ok": False,
                    "error": str(e),
                    "needs_user_help": True,
                    "result": {"status": "failed", "error": str(e)}
                }
    
    def _update_session_context(self, agent_result: Dict, agent_type: str):
        """Update workflow state based on agent results"""
        if agent_type == "authentication":
            if agent_result.get("result", {}).get("status") == "logged_in":
                self.state.session_context["auth_status"] = "logged_in"
        
        elif agent_type == "shopping":
            # Extract cart items from result
            if agent_result.get("terminated"):
                # Shopping completed
                self.state.session_context["checkout_progress"] = "ready_for_payment"
            # Try to extract shopping list from trace if available
            if agent_result.get("trace"):
                shopping_items = []
                for trace_item in agent_result.get("trace", []):
                    if trace_item.get("tool") == "fill_role" and "value" in trace_item.get("args", {}):
                        shopping_items.append(trace_item["args"]["value"])
                if shopping_items:
                    self.state.session_context["cart_items"] = shopping_items


__all__ = ["ConversationWorkflow", "ConversationState"]

