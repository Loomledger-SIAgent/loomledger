"""YAML/JSON specification schemas for nodes, agents, and graphs."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import yaml
from pydantic import Field

from loomledger._compat import CompatModel, field_Validator, model_Validator
from loomledger.models.contracts import DecisionQuestion, is_moving_version

TEXT_PAYLOAD_SCHEMA = "TextPayload"


class NodeKind(str, Enum):
    AGENT = "agent"
    LLM = "llm"
    DECIDE = "decide"
    EMBED = "embed"
    TOOL = "tool"


class ModelSpec(CompatModel):
    """Model binding in a node spec, enforcing pinned versions and secret:// references."""

    provider: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    secret_ref: Optional[str] = None
    fallback: Optional["ModelSpec"] = None

    @field_Validator("version")
    def _validate_pinned_version(cls, v: str) -> str:
        if is_moving_version(v):
            raise ValueError(
                f"Unpinned model version '{v}' is rejected in saved specs; specify an exact version."
            )
        return v

    @field_Validator("secret_ref")
    def _validate_secret_ref(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not v.startswith("secret://") or len(v) <= len("secret://"):
            raise ValueError(
                "secret_ref must be a secret URI starting with 'secret://' (never store raw API keys in specs)."
            )
        return v


ModelSpec.update_forward_refs()


class PortSchemaSpec(CompatModel):
    """Typed input/output port contract. Defaults to strict schema enforcement."""

    schema_name: str = Field(..., min_length=1)
    fields: Dict[str, str] = Field(default_factory=dict)

    @classmethod
    def free_text(cls) -> "PortSchemaSpec":
        """Explicit opt-out for free-text LLM output."""
        return cls(schema_name=TEXT_PAYLOAD_SCHEMA, fields={"text": "str"})


class LimitsSpec(CompatModel):
    max_tokens: int = Field(default=4096, gt=0)
    max_cost_usd: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    timeout_ms: int = Field(default=30000, gt=0)
    max_steps: int = Field(default=1, ge=1, le=100)
    allowed_tools: List[str] = Field(default_factory=list)
    require_human_approval_for: List[str] = Field(default_factory=list)


class NodeSpec(CompatModel):
    """Versioned specification for a graph node (agent, llm, decide, embed, or tool)."""

    id: str = Field(..., min_length=1)
    kind: NodeKind
    role: str = Field(..., min_length=1)
    context: str = ""
    task: str = ""
    model: Optional[ModelSpec] = None
    questions: Dict[str, DecisionQuestion] = Field(default_factory=dict)
    limits: LimitsSpec = Field(default_factory=LimitsSpec)
    inputs: PortSchemaSpec
    outputs: PortSchemaSpec
    estimated_state_bytes: Optional[int] = Field(default=None, ge=0)

    @model_Validator
    def _validate_node_kind_rules(self) -> "NodeSpec":
        if self.kind in (NodeKind.AGENT, NodeKind.LLM, NodeKind.DECIDE, NodeKind.EMBED):
            if self.model is None:
                raise ValueError(f"Node '{self.id}' of kind '{self.kind.value}' requires a 'model' block.")
        if self.kind == NodeKind.AGENT and self.limits.max_steps < 2:
            raise ValueError(
                f"Node '{self.id}' has kind='agent' (tool loop) which requires limits.max_steps >= 2; "
                "use kind='llm' for single-shot calls."
            )
        if self.kind == NodeKind.LLM and (self.limits.max_steps > 1 or self.limits.allowed_tools):
            raise ValueError(
                f"Node '{self.id}' has kind='llm' (single-shot) and cannot declare a tool loop or allowed_tools; "
                "use kind='agent' instead."
            )
        if self.kind == NodeKind.DECIDE and not self.questions:
            raise ValueError(f"Decision node '{self.id}' (kind='decide') must define at least one question.")
        if self.kind != NodeKind.DECIDE and self.questions:
            raise ValueError(f"Only kind='decide' nodes may declare 'questions' (found on '{self.id}').")
        return self


class EdgeCondition(CompatModel):
    """Optional conditional routing gate on a graph edge (e.g., branching on a Decide node's answer)."""

    question_key: Optional[str] = None
    expected_choice: Optional[str] = None
    min_noul: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_score: Optional[float] = None
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    escalate_on_low_confidence: bool = False


class EdgeSpec(CompatModel):
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    condition: Optional[EdgeCondition] = None


class GraphSpec(CompatModel):
    """Complete workflow graph specification (source of truth for both CLI and React Flow canvas)."""

    id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    description: str = ""
    budget_max_tokens: Optional[int] = Field(default=None, gt=0)
    budget_max_cost_usd: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    nodes: List[NodeSpec]
    edges: List[EdgeSpec] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, yaml_text: str) -> "GraphSpec":
        return cls.from_obj(yaml.safe_load(yaml_text))

    @classmethod
    def from_yaml_file(cls, path: Path) -> "GraphSpec":
        return cls.from_yaml(path.read_text(encoding="utf-8"))
