"""Model layer contracts: Request/Response kinds, Capabilities, Usage, and Envelope."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Protocol, Set, Union
from pydantic import Field

from loomledger._compat import CompatModel, field_Validator, model_Validator

MOVING_VERSION_ALIASES = {"latest", "jev-latest", "~typesafe/jev-latest", "auto", "default"}


def is_moving_version(version: str) -> bool:
    v = version.strip().lower()
    return (
        not v
        or v in MOVING_VERSION_ALIASES
        or v.endswith("-latest")
        or v.endswith(":latest")
        or v.startswith("~")
    )


class ModelId(CompatModel):
    """Uniquely identifies a provider, model name, and pinned version."""

    provider: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)

    @field_Validator("version")
    def _reject_moving_alias(cls, v: str) -> str:
        if is_moving_version(v):
            raise ValueError(
                f"Model version '{v}' is a moving alias; saved specs and audit logs require a pinned version."
            )
        return v

    @property
    def canonical_id(self) -> str:
        return f"{self.provider}/{self.name}@{self.version}"


class Usage(CompatModel):
    """Normalized token and cost accounting. Unknown fields remain None, never 0."""

    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    cached_tokens: Optional[int] = Field(default=None, ge=0)
    reasoning_tokens: Optional[int] = Field(default=None, ge=0)
    cost_usd: Optional[Decimal] = Field(default=None, ge=Decimal("0"))


class Capabilities(CompatModel):
    """Declared model capabilities checked at spec validation time and before invocation."""

    kinds: Set[Literal["generate", "decide", "embed"]]
    decision_primitives: Set[Literal["noul", "choice", "score", "box"]] = Field(default_factory=set)
    tools: bool = False
    structured_output: Literal["native", "tool", "json_mode", "none"] = "none"
    vision: bool = False
    default_context: Optional[int] = Field(default=None, gt=0)
    max_context: Optional[int] = Field(default=None, gt=0)

    @model_Validator
    def _validate_capabilities(self) -> "Capabilities":
        if not self.kinds:
            raise ValueError("Capabilities.kinds must contain at least one capability kind.")
        if "decide" in self.kinds and not self.decision_primitives:
            raise ValueError("A 'decide' model must declare at least one decision primitive.")
        if "box" in self.decision_primitives and not self.vision:
            raise ValueError("The 'box' decision primitive requires vision=True.")
        if (
            self.default_context is not None
            and self.max_context is not None
            and self.default_context > self.max_context
        ):
            raise ValueError("default_context cannot exceed max_context.")
        return self


class StopReason(str, Enum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class ToolDefinition(CompatModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    destructive: bool = False


class ToolCall(CompatModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    args: Dict[str, Any] = Field(default_factory=dict)


class ContentBlock(CompatModel):
    type: Literal["text", "image_url", "tool_call", "tool_result"]
    text: Optional[str] = None
    image_url: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    tool_call_id: Optional[str] = None
    tool_output: Optional[Any] = None


class Message(CompatModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: List[ContentBlock]


# --- Decision Model (System One / OpenRouter Decisions API) Primitives ---

class NoulQuestion(CompatModel):
    type: Literal["noul"] = "noul"
    instructions: str = Field(..., min_length=1)
    criteria: Dict[str, str] = Field(default_factory=dict)


class ChoiceQuestion(CompatModel):
    type: Literal["choice"] = "choice"
    instructions: str = Field(..., min_length=1)
    criteria: Dict[str, str]

    @field_Validator("criteria")
    def _check_choice_bounds(cls, v: Dict[str, str]) -> Dict[str, str]:
        if len(v) < 2 or len(v) > 255:
            raise ValueError("ChoiceQuestion requires between 2 and 255 options in criteria.")
        return v


class ScoreQuestion(CompatModel):
    type: Literal["score"] = "score"
    instructions: str = Field(..., min_length=1)
    criteria: List[str]

    @field_Validator("criteria")
    def _check_score_bounds(cls, v: List[str]) -> List[str]:
        if len(v) < 2 or len(v) > 10:
            raise ValueError("ScoreQuestion requires between 2 and 10 ordered rubric levels.")
        return v


class BoxQuestion(CompatModel):
    type: Literal["box"] = "box"
    instructions: str = Field(..., min_length=1)


DecisionQuestion = Union[NoulQuestion, ChoiceQuestion, ScoreQuestion, BoxQuestion]


class NoulAnswer(CompatModel):
    type: Literal["noul"] = "noul"
    noul: float = Field(..., ge=0.0, le=1.0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ChoiceAnswer(CompatModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: Dict[str, float]
    confidence: float = Field(..., ge=0.0, le=1.0)


class ScoreAnswer(CompatModel):
    type: Literal["score"] = "score"
    score: float
    probabilities: List[float]
    confidence: float = Field(..., ge=0.0, le=1.0)


class BoundingBox(CompatModel):
    top: float = Field(..., ge=0.0, le=1.0)
    bottom: float = Field(..., ge=0.0, le=1.0)
    left: float = Field(..., ge=0.0, le=1.0)
    right: float = Field(..., ge=0.0, le=1.0)

    @model_Validator
    def _check_box_order(self) -> "BoundingBox":
        if self.top > self.bottom:
            raise ValueError("BoundingBox.top must be <= bottom.")
        if self.left > self.right:
            raise ValueError("BoundingBox.left must be <= right.")
        return self


class BoxAnswer(CompatModel):
    type: Literal["box"] = "box"
    box: BoundingBox
    confidence: float = Field(..., ge=0.0, le=1.0)


DecisionAnswer = Union[NoulAnswer, ChoiceAnswer, ScoreAnswer, BoxAnswer]


# --- Canonical Request & Response Unions ---

class GenerateRequest(CompatModel):
    kind: Literal["generate"] = "generate"
    messages: List[Message]
    tools: List[ToolDefinition] = Field(default_factory=list)
    output_schema: Optional[Dict[str, Any]] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, gt=0)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class GenerateResponse(CompatModel):
    kind: Literal["generate"] = "generate"
    model_id: ModelId
    content: List[ContentBlock] = Field(default_factory=list)
    structured_output: Optional[Dict[str, Any]] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = StopReason.END_TURN
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = Field(default=0, ge=0)
    raw_provider_hash: Optional[str] = None


class DecideRequest(CompatModel):
    kind: Literal["decide"] = "decide"
    state: Any
    questions: Dict[str, DecisionQuestion]
    provider_options: Dict[str, Any] = Field(default_factory=dict)

    @field_Validator("questions")
    def _non_empty_questions(cls, v: Dict[str, DecisionQuestion]) -> Dict[str, DecisionQuestion]:
        if not v:
            raise ValueError("DecideRequest.questions must contain at least one question.")
        return v


class DecideResponse(CompatModel):
    kind: Literal["decide"] = "decide"
    model_id: ModelId
    answers: Dict[str, DecisionAnswer]
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = Field(default=0, ge=0)
    long_context_mode: bool = False
    raw_provider_hash: Optional[str] = None


class EmbedRequest(CompatModel):
    kind: Literal["embed"] = "embed"
    inputs: List[str]
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class EmbedResponse(CompatModel):
    kind: Literal["embed"] = "embed"
    model_id: ModelId
    embeddings: List[List[float]]
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = Field(default=0, ge=0)
    raw_provider_hash: Optional[str] = None


Request = Union[GenerateRequest, DecideRequest, EmbedRequest]
Response = Union[GenerateResponse, DecideResponse, EmbedResponse]


class CallContext(CompatModel):
    run_id: str
    node_id: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    budget_remaining_tokens: Optional[int] = None
    budget_remaining_usd: Optional[Decimal] = None


class Envelope(CompatModel):
    """Neutral typed payload envelope exchanged across node ports."""

    schema_name: str = Field(..., min_length=1)
    payload: Dict[str, Any]
    trace_id: str = Field(..., min_length=1)
    span_id: str = Field(..., min_length=1)
    parent_span_id: Optional[str] = None
    usage: Optional[Usage] = None
    model_id: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ModelNode(Protocol):
    """Unified model adapter contract implemented by LLM and non-LLM providers."""

    id: ModelId
    capabilities: Capabilities

    async def invoke(self, req: Request, ctx: CallContext) -> Response: ...
