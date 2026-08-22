"""Deterministic mock LLM client for testing intelligence pipelines."""

from typing import TypeVar

from pydantic import BaseModel

from app.adapters.llm.base import LLMClientProtocol, LLMRequest, LLMResponse

T = TypeVar("T", bound=BaseModel)


class MockLLMClient(LLMClientProtocol):
    """Deterministic, provider-neutral mock LLM client."""

    def __init__(
        self,
        default_response_text: str = "Mock generated analysis.",
        default_structured_payloads: dict[type[BaseModel], BaseModel] | None = None,
    ) -> None:
        self.default_response_text = default_response_text
        self.structured_payloads: dict[type[BaseModel], BaseModel] = (
            default_structured_payloads or {}
        )
        self.recorded_requests: list[LLMRequest] = []
        self.recorded_structured_prompts: list[tuple[str, str, type[BaseModel]]] = []

    def set_structured_response(
        self, schema_cls: type[T], response_instance: T
    ) -> None:
        """Register a specific mock instance to be returned when schema_cls is requested."""
        self.structured_payloads[schema_cls] = response_instance

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        """Record request and return deterministic text response."""
        self.recorded_requests.append(request)
        return LLMResponse(
            content=self.default_response_text,
            structured_output=None,
            tool_calls=(),
            prompt_tokens=25,
            completion_tokens=50,
            total_tokens=75,
            model_name="mock-llm",
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[T],
        temperature: float = 0.0,
    ) -> T:
        """Record prompt and return registered structured response matching response_schema."""
        _ = temperature  # Unused in deterministic mock
        self.recorded_structured_prompts.append(
            (system_prompt, user_prompt, response_schema)
        )

        if response_schema in self.structured_payloads:
            instance = self.structured_payloads[response_schema]
            if isinstance(instance, response_schema):
                return instance

        # Fallback: attempt default instantiation if all fields have defaults
        try:
            return response_schema.model_validate({})
        except Exception as e:
            raise ValueError(
                f"No mock response configured for schema {response_schema.__name__}. "
                f"Use `mock_client.set_structured_response()` to provide one."
            ) from e
