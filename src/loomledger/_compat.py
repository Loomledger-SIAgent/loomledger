"""Compatibility helpers supporting both Pydantic v2 and Pydantic v1.10+ runtimes."""

from __future__ import annotations

from typing import Any, Callable
import pydantic
from pydantic import BaseModel

PYDANTIC_V2 = int(pydantic.__version__.split(".")[0]) >= 2

if PYDANTIC_V2:
    from pydantic import ConfigDict, field_validator, model_validator
else:
    from pydantic import root_validator, validator


def model_Validator(fn: Callable[..., Any]) -> Any:
    """Cross-version model validator (runs after field validation)."""
    if PYDANTIC_V2:
        return model_validator(mode="after")(fn)

    def _v1_wrapper(cls: Any, values: dict[str, Any]) -> dict[str, Any]:
        instance = cls.construct(**values)
        validated = fn(instance)
        return validated.__dict__

    return root_validator(pre=False, allow_reuse=True)(_v1_wrapper)


def field_Validator(*fields: str) -> Callable[[Callable[..., Any]], Any]:
    """Cross-version field validator."""
    def _decorator(fn: Callable[..., Any]) -> Any:
        if PYDANTIC_V2:
            return field_validator(*fields)(classmethod(fn))
        return validator(*fields, allow_reuse=True)(classmethod(fn))
    return _decorator


class CompatModel(BaseModel):
    """Base model exposing uniform .to_dict() and .from_obj() helpers across Pydantic v1/v2."""

    if PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid", validate_assignment=True)
    else:
        class Config:
            extra = "forbid"
            validate_assignment = True

    def to_dict(self) -> dict[str, Any]:
        if PYDANTIC_V2:
            return self.model_dump(mode="python")
        return self.dict()

    @classmethod
    def from_obj(cls, obj: Any) -> Any:
        if PYDANTIC_V2:
            return cls.model_validate(obj)
        return cls.parse_obj(obj)
