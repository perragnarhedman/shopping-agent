from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from openai import AsyncOpenAI
from src.utils.config_loader import ConfigLoader
from src.core.schema_validator import SchemaValidator


class ConversationAgent:
    """
    Manages natural language conversations and orchestrates specialized agents.
    Does NOT use ToolEnv - pure LLM reasoning for intent recognition.
    """
    
    def __init__(self):
        cfg = ConfigLoader.load_global_config()
        agents_cfg = cfg.get("agents", {})
        self._model = agents_cfg.get("model", "gpt-4o-mini")
        self._temperature = 0.3  # Slightly creative for natural conversation
        self._client = AsyncOpenAI()
        self._logger = logging.getLogger(__name__)
        self._validator = SchemaValidator("src/agents/schemas/conversation_response.schema.json")
    
    async def run(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        session_context: Dict[str, Any],
        clarification_count: int = 0
    ) -> Dict[str, Any]:
        """
        Process user message and return structured decision.
        
        Args:
            user_message: Current user input
            conversation_history: List of {"role": "user"/"assistant", "content": "..."}
            session_context: {"cart_items": [...], "auth_status": "...", ...}
            clarification_count: Number of consecutive clarifications
        
        Returns:
            Validated JSON response matching conversation_response.schema.json
        """
        # Load system prompt
        with open("src/agents/prompts/conversation_system.txt", "r", encoding="utf-8") as f:
            system_prompt = f.read()
        
        # Build messages for OpenAI
        messages = self._build_messages(
            system_prompt,
            conversation_history,
            user_message,
            session_context,
            clarification_count
        )
        
        # Get LLM response in JSON mode
        response = await self._get_structured_response(messages)
        
        # Validate against schema
        validated = self._validate_and_enhance(response, clarification_count)
        
        return validated
    
    def _build_messages(
        self,
        system_prompt: str,
        conversation_history: List[Dict],
        user_message: str,
        session_context: Dict,
        clarification_count: int
    ) -> List[Dict]:
        """Build message array for OpenAI API"""
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history (last 50 messages to avoid token limits)
        recent_history = conversation_history[-50:] if len(conversation_history) > 50 else conversation_history
        messages.extend(recent_history)
        
        # Add current user message with context
        context_info = f"\n\n[SESSION_CONTEXT: {json.dumps(session_context)}]" if session_context else ""
        clarification_info = f"\n[CLARIFICATION_COUNT: {clarification_count}]" if clarification_count > 0 else ""
        
        messages.append({
            "role": "user",
            "content": f"{user_message}{context_info}{clarification_info}"
        })
        
        return messages
    
    async def _get_structured_response(self, messages: List[Dict]) -> Dict[str, Any]:
        """Call OpenAI with JSON mode"""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                messages=messages,
                response_format={"type": "json_object"},
                timeout=30
            )
            
            content = response.choices[0].message.content
            return json.loads(content)
        
        except json.JSONDecodeError as e:
            self._logger.error(f"Failed to parse LLM response as JSON: {e}")
            # Fallback response
            return {
                "intent": "clarification_needed",
                "confidence": 0.0,
                "user_message_understood": "Could not parse response",
                "extracted_info": None,
                "clarification_questions": [],
                "agent_delegation": {"required": False, "agent_type": None, "task_payload": None},
                "conversation_response": "I'm having trouble understanding. Could you rephrase that?",
                "next_action": "await_user_input",
                "needs_human_escalation": False
            }
        
        except Exception as e:
            self._logger.error(f"Error calling OpenAI: {e}")
            raise
    
    def _validate_and_enhance(self, response: Dict, clarification_count: int) -> Dict[str, Any]:
        """Validate against schema and apply business logic"""
        # Schema validation
        is_valid, errors = self._validator.validate(response)
        if not is_valid:
            self._logger.error(f"Schema validation failed: {errors}")
            # Return safe fallback
            return {
                "intent": "clarification_needed",
                "confidence": 0.0,
                "user_message_understood": "Validation error",
                "extracted_info": None,
                "clarification_questions": [],
                "agent_delegation": {"required": False, "agent_type": None, "task_payload": None},
                "conversation_response": "I'm having trouble processing that. Could you try again?",
                "next_action": "await_user_input",
                "needs_human_escalation": False
            }
        
        # Business logic constraints
        
        # 1. Escalate after 3 clarifications
        if clarification_count >= 3:
            response["needs_human_escalation"] = True
            response["conversation_response"] = "I'm having trouble understanding. Let me get you some help."
            response["next_action"] = "await_user_input"
            response["agent_delegation"]["required"] = False
        
        # 2. Force clarification if low confidence
        if response.get("confidence", 0) < 0.5:
            response["next_action"] = "await_user_input"
            response["agent_delegation"]["required"] = False
        
        # 3. Never delegate for out-of-scope
        if response.get("intent") == "out_of_scope":
            response["agent_delegation"]["required"] = False
        
        # 4. Validate delegation payload
        if response.get("agent_delegation", {}).get("required"):
            payload = response["agent_delegation"].get("task_payload")
            if not payload or (
                response["agent_delegation"]["agent_type"] == "shopping" 
                and not payload.get("shopping_list")
            ):
                # Invalid payload - force clarification
                response["next_action"] = "await_user_input"
                response["agent_delegation"]["required"] = False
                response["conversation_response"] = "What would you like to shop for?"
        
        return response


__all__ = ["ConversationAgent"]

