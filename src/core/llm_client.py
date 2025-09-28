from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from src.core.schema_validator import json_schema, try_validate_and_parse, load_json_schema_from_file, try_validate_with_jsonschema
from src.utils.retry_handler import retry_async
import logging
import logging


ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMClient:
    def __init__(self, *, model: str | None = None, temperature: float = 0.0, max_output_tokens: int | None = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._logger = logging.getLogger(__name__)

    async def complete_json(self, *, system_prompt: str, user_prompt: str, response_model: Type[ModelT], max_validation_attempts: int = 2) -> ModelT:
        """Request a JSON-typed response and validate against response_model. Retries on validation failures."""
        schema_dict = json_schema(response_model)
        self._logger.debug(
            "LLM request %s",
            json.dumps({
                "model": self._model,
                "temperature": self._temperature,
                "system_prompt": _truncate(system_prompt),
                "user_prompt": _truncate(user_prompt),
            }),
        )

        async def _op() -> ModelT:
            content = await self._chat_completion_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=schema_dict)
            data = _extract_first_tool_or_text_json(content)
            self._logger.debug(
                "LLM raw response %s",
                _truncate(json.dumps(content, ensure_ascii=False)),
            )
            model, errors = try_validate_and_parse(response_model, data)
            if model is None:
                raise ValueError(f"Validation failed: {errors}")
            return model

        # Retry both network and validation errors with small backoff
        attempts = 0
        last_exc: Exception | None = None
        while attempts <= max_validation_attempts:
            try:
                return await retry_async(_op, retries=1)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                attempts += 1
        raise last_exc  # type: ignore[misc]

    async def complete_json_with_schema(self, *, system_prompt: str, user_prompt: str, schema: Dict[str, Any], max_validation_attempts: int = 2) -> Dict[str, Any]:
        """Request a JSON-typed response and validate against a JSON Schema dict."""
        self._logger.debug(
            "LLM request %s",
            json.dumps({
                "model": self._model,
                "temperature": self._temperature,
                "system_prompt": _truncate(system_prompt),
                "user_prompt": _truncate(user_prompt),
            }),
        )

        async def _op() -> Dict[str, Any]:
            content = await self._chat_completion_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=schema)
            data = _extract_first_tool_or_text_json(content)
            self._logger.debug(
                "LLM raw response %s",
                _truncate(json.dumps(content, ensure_ascii=False)),
            )
            ok, errors = try_validate_with_jsonschema(schema, data)
            if not ok:
                raise ValueError(f"Validation failed: {errors}")
            return data

        attempts = 0
        last_exc: Exception | None = None
        while attempts <= max_validation_attempts:
            try:
                return await retry_async(_op, retries=1)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                attempts += 1
        raise last_exc  # type: ignore[misc]

    async def _chat_completion_json(self, *, system_prompt: str, user_prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": {"name": "response", "schema": schema}},
            max_tokens=self._max_output_tokens,
        )
        choice = response.choices[0]
        message = choice.message
        # OpenAI python client returns content as string when using JSON schema
        if message.content is None:
            raise ValueError("Empty response content from LLM")
        try:
            return json.loads(message.content)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("LLM returned non-JSON content") from exc


def _extract_first_tool_or_text_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    # For now the content is already parsed JSON per _chat_completion_json, so return as-is.
    return payload


def _truncate(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


__all__ = ["LLMClient"]


