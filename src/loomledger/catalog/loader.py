"""Versioned model capability and pricing catalog loader."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yaml

from loomledger._compat import CompatModel
from loomledger.models.contracts import Capabilities, ModelId, Usage

DEFAULT_CATALOG_PATH = Path(__file__).with_name("models.yaml")
ONE_MILLION = Decimal("1000000")


class ModelPrice(CompatModel):
    input_per_1m_usd: Decimal
    output_per_1m_usd: Decimal = Decimal("0.00")
    cached_input_per_1m_usd: Optional[Decimal] = None


class CatalogEntry(CompatModel):
    provider: str
    name: str
    version: str
    capabilities: Capabilities
    pricing: ModelPrice

    @property
    def model_id(self) -> ModelId:
        return ModelId(provider=self.provider, name=self.name, version=self.version)


class ModelCatalog(CompatModel):
    catalog_version: str
    models: List[CatalogEntry]

    @classmethod
    def load_default(cls) -> "ModelCatalog":
        return cls.load_from_file(DEFAULT_CATALOG_PATH)

    @classmethod
    def load_from_file(cls, path: Path) -> "ModelCatalog":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.from_obj(raw)

    def _index(self) -> Dict[Tuple[str, str, str], CatalogEntry]:
        return {(m.provider, m.name, m.version): m for m in self.models}

    def get(self, provider: str, name: str, version: str) -> Optional[CatalogEntry]:
        return self._index().get((provider, name, version))

    def require(self, provider: str, name: str, version: str) -> CatalogEntry:
        entry = self.get(provider, name, version)
        if entry is None:
            raise KeyError(
                f"Model '{provider}/{name}@{version}' not found in catalog version {self.catalog_version}."
            )
        return entry

    def compute_cost_usd(self, provider: str, name: str, version: str, usage: Usage) -> Optional[Decimal]:
        """Compute exact USD cost from the versioned catalog. Returns None if token counts are unknown."""
        if usage.input_tokens is None and usage.output_tokens is None:
            return None
        entry = self.require(provider, name, version)
        price = entry.pricing

        in_tokens = Decimal(usage.input_tokens or 0)
        cached_tokens = Decimal(usage.cached_tokens or 0)
        billable_unached_in = max(Decimal("0"), in_tokens - cached_tokens)
        out_tokens = Decimal(usage.output_tokens or 0) + Decimal(usage.reasoning_tokens or 0)

        cached_rate = (
            price.cached_input_per_1m_usd
            if price.cached_input_per_1m_usd is not None
            else price.input_per_1m_usd
        )
        cost = (
            (billable_unached_in * price.input_per_1m_usd)
            + (cached_tokens * cached_rate)
            + (out_tokens * price.output_per_1m_usd)
        ) / ONE_MILLION
        return cost.quantize(Decimal("0.00000001"))
