"""Static graph, port schema, and model capability validator."""

from __future__ import annotations

from typing import Dict, List, Set
from pydantic import Field

from loomledger._compat import CompatModel
from loomledger.catalog.loader import CatalogEntry, ModelCatalog
from loomledger.specs.schemas import GraphSpec, ModelSpec, NodeKind, NodeSpec

JEV_FAST_MODE_BYTES = 32_000


class ValidationReport(CompatModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class SpecValidator:
    """Validates NodeSpecs and GraphSpecs against the versioned ModelCatalog."""

    def __init__(self, catalog: ModelCatalog) -> None:
        self.catalog = catalog

    def validate_graph(self, graph: GraphSpec) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []

        nodes_by_id: Dict[str, NodeSpec] = {}
        for node in graph.nodes:
            if node.id in nodes_by_id:
                errors.append(f"Duplicate node id '{node.id}' in graph '{graph.id}'.")
            nodes_by_id[node.id] = node
            node_report = self.validate_node(node)
            errors.extend(node_report.errors)
            warnings.extend(node_report.warnings)

        # Validate edges & port schema matching
        adj: Dict[str, List[str]] = {nid: [] for nid in nodes_by_id}
        for edge in graph.edges:
            if edge.source not in nodes_by_id:
                errors.append(f"Edge references unknown source node '{edge.source}'.")
                continue
            if edge.target not in nodes_by_id:
                errors.append(f"Edge references unknown target node '{edge.target}'.")
                continue
            src_node = nodes_by_id[edge.source]
            dst_node = nodes_by_id[edge.target]
            adj[edge.source].append(edge.target)

            if src_node.outputs.schema_name != dst_node.inputs.schema_name:
                errors.append(
                    f"Port type mismatch on edge '{edge.source} -> {edge.target}': "
                    f"source outputs '{src_node.outputs.schema_name}' but target expects "
                    f"'{dst_node.inputs.schema_name}'."
                )
            elif src_node.outputs.fields and dst_node.inputs.fields:
                for field_name, expected_type in dst_node.inputs.fields.items():
                    actual_type = src_node.outputs.fields.get(field_name)
                    if actual_type != expected_type:
                        errors.append(
                            f"Port field mismatch on edge '{edge.source} -> {edge.target}' "
                            f"for field '{field_name}': source has '{actual_type}', "
                            f"target expects '{expected_type}'."
                        )

            if edge.condition and edge.condition.question_key:
                if src_node.kind != NodeKind.DECIDE:
                    errors.append(
                        f"Edge '{edge.source} -> {edge.target}' specifies question_key "
                        f"'{edge.condition.question_key}', but source node '{src_node.id}' is not kind='decide'."
                    )
                elif edge.condition.question_key not in src_node.questions:
                    errors.append(
                        f"Edge '{edge.source} -> {edge.target}' references unknown question_key "
                        f"'{edge.condition.question_key}' on decide node '{src_node.id}'."
                    )

        # Detect cycles in graph
        if self._has_cycle(adj):
            errors.append(f"Graph '{graph.id}' contains a cycle; workflow graphs must be DAGs.")

        return ValidationReport(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_node(self, node: NodeSpec) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []

        if node.model is None:
            return ValidationReport(valid=True, errors=errors, warnings=warnings)

        entry = self.catalog.get(node.model.provider, node.model.name, node.model.version)
        if entry is None:
            errors.append(
                f"Node '{node.id}' references model "
                f"'{node.model.provider}/{node.model.name}@{node.model.version}' "
                f"which is not in catalog v{self.catalog.catalog_version}."
            )
            return ValidationReport(valid=False, errors=errors, warnings=warnings)

        self._check_node_against_catalog_entry(node, entry, is_fallback=False, errors=errors, warnings=warnings)

        if node.model.fallback is not None:
            fb: ModelSpec = node.model.fallback
            fb_entry = self.catalog.get(fb.provider, fb.name, fb.version)
            if fb_entry is None:
                errors.append(
                    f"Node '{node.id}' fallback model '{fb.provider}/{fb.name}@{fb.version}' "
                    f"is not in catalog v{self.catalog.catalog_version}."
                )
            else:
                self._check_node_against_catalog_entry(
                    node, fb_entry, is_fallback=True, errors=errors, warnings=warnings
                )

        return ValidationReport(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def _check_node_against_catalog_entry(
        self,
        node: NodeSpec,
        entry: CatalogEntry,
        is_fallback: bool,
        errors: List[str],
        warnings: List[str],
    ) -> None:
        caps = entry.capabilities
        label = "fallback model" if is_fallback else "model"
        mid = entry.model_id.canonical_id

        if node.kind in (NodeKind.AGENT, NodeKind.LLM):
            if "generate" not in caps.kinds:
                errors.append(
                    f"Node '{node.id}' ({node.kind.value}) requires 'generate' capability, "
                    f"but {label} '{mid}' only supports {sorted(caps.kinds)}."
                )
            if node.limits.allowed_tools and not caps.tools:
                errors.append(
                    f"Node '{node.id}' declares allowed_tools {node.limits.allowed_tools}, "
                    f"but {label} '{mid}' has tools=False."
                )

        elif node.kind == NodeKind.DECIDE:
            # A fallback on a decide node can be either a 'decide' model OR a 'generate' LLM with structured output
            if not is_fallback and "decide" not in caps.kinds:
                errors.append(
                    f"Node '{node.id}' (decide) requires 'decide' capability, "
                    f"but model '{mid}' only supports {sorted(caps.kinds)}."
                )
            if is_fallback and "decide" not in caps.kinds and "generate" not in caps.kinds:
                errors.append(
                    f"Node '{node.id}' (decide) fallback model '{mid}' must support 'decide' or 'generate'."
                )
            if "decide" in caps.kinds:
                q_types = {q.type for q in node.questions.values()}
                for q_name, q in node.questions.items():
                    if q.type not in caps.decision_primitives:
                        errors.append(
                            f"Node '{node.id}' question '{q_name}' uses primitive '{q.type}', "
                            f"which is not supported by {label} '{mid}' "
                            f"(supported: {sorted(caps.decision_primitives)})."
                        )
                if "box" in q_types and "noul" not in q_types:
                    warnings.append(
                        f"Node '{node.id}' uses a 'box' question without a paired 'noul' presence question; "
                        "Box always returns four coordinates even when the target is absent."
                    )
                if (
                    node.estimated_state_bytes is not None
                    and node.estimated_state_bytes > JEV_FAST_MODE_BYTES
                ):
                    warnings.append(
                        f"Node '{node.id}' estimated_state_bytes ({node.estimated_state_bytes}) exceeds "
                        f"{JEV_FAST_MODE_BYTES} bytes; System One models will run in slower long-context mode."
                    )

        elif node.kind == NodeKind.EMBED:
            if "embed" not in caps.kinds:
                errors.append(
                    f"Node '{node.id}' (embed) requires 'embed' capability, "
                    f"but {label} '{mid}' only supports {sorted(caps.kinds)}."
                )

    @staticmethod
    def _has_cycle(adj: Dict[str, List[str]]) -> bool:
        visited: Set[str] = set()
        in_stack: Set[str] = set()

        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            in_stack.add(node_id)
            for nxt in adj.get(node_id, []):
                if nxt not in visited:
                    if dfs(nxt):
                        return True
                elif nxt in in_stack:
                    return True
            in_stack.remove(node_id)
            return False

        for nid in adj:
            if nid not in visited and dfs(nid):
                return True
        return False
