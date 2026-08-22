"""Strict DAG validation and deterministic topological sorting engine."""

from collections import deque
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.common.errors import DAGValidationError
from app.state.models import ResearchPlan

# Safety constraints for graph execution
MAX_NODES_LIMIT: Final[int] = 100
MAX_DEPTH_LIMIT: Final[int] = 10
MAX_FAN_OUT_LIMIT: Final[int] = 20


class DAGMetrics(BaseModel):
    """Structural metrics computed during DAG validation."""

    model_config = ConfigDict(frozen=True)

    node_count: int
    edge_count: int
    critical_path_depth: int
    max_fan_out: int
    root_node_ids: tuple[str, ...]
    leaf_node_ids: tuple[str, ...]


class ValidatedDAG(BaseModel):
    """Result of successful DAG validation containing deterministic execution order."""

    model_config = ConfigDict(frozen=True)

    plan_id: str
    run_id: str
    topological_order: tuple[str, ...]
    metrics: DAGMetrics
    node_dependencies: dict[str, tuple[str, ...]] = Field(
        description="Map of node_id to its prerequisite parent node IDs"
    )
    node_dependents: dict[str, tuple[str, ...]] = Field(
        description="Map of node_id to its downstream child node IDs"
    )


class DAGValidator:
    """Validator enforcing structural correctness, acyclicity, and safety limits."""

    def __init__(
        self,
        max_nodes: int = MAX_NODES_LIMIT,
        max_depth: int = MAX_DEPTH_LIMIT,
        max_fan_out: int = MAX_FAN_OUT_LIMIT,
    ) -> None:
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.max_fan_out = max_fan_out

    def validate_plan(self, plan: ResearchPlan) -> ValidatedDAG:
        """Validate research plan graph and return deterministic execution metadata."""
        nodes = plan.nodes
        edges = plan.edges

        # 1. Non-empty nodes check
        if not nodes:
            raise DAGValidationError(
                message="Research plan contains no task nodes",
                error_code="EMPTY_GRAPH",
            )

        # 2. Maximum nodes limit check
        if len(nodes) > self.max_nodes:
            raise DAGValidationError(
                message=f"Plan exceeds maximum allowed nodes limit ({len(nodes)} > {self.max_nodes})",
                error_code="MAX_NODES_EXCEEDED",
                violating_nodes=list(nodes.keys()),
            )

        # 3. Validate each node structure
        for node_id, node in nodes.items():
            if node.subtask_id != node_id:
                raise DAGValidationError(
                    message=f"Node key '{node_id}' does not match subtask_id '{node.subtask_id}'",
                    error_code="NODE_KEY_MISMATCH",
                    violating_nodes=[node_id],
                )
            if not node.objective.strip():
                raise DAGValidationError(
                    message=f"Node '{node_id}' has empty objective",
                    error_code="EMPTY_OBJECTIVE",
                    violating_nodes=[node_id],
                )

        # Build adjacency lists and in-degree map
        # in_edges: target -> set of sources (prerequisites)
        # out_edges: source -> set of targets (dependents)
        in_edges: dict[str, set[str]] = {nid: set() for nid in nodes}
        out_edges: dict[str, set[str]] = {nid: set() for nid in nodes}
        seen_edges: set[tuple[str, str]] = set()

        for edge in edges:
            src = edge.source_id
            tgt = edge.target_id

            # 4. Self-dependency check
            if src == tgt:
                raise DAGValidationError(
                    message=f"Self-dependency detected: node '{src}' depends on itself",
                    error_code="SELF_DEPENDENCY",
                    violating_nodes=[src],
                )

            # 5. Missing node references check
            if src not in nodes:
                raise DAGValidationError(
                    message=f"Dependency edge references non-existent source node '{src}'",
                    error_code="MISSING_SOURCE_NODE",
                    violating_nodes=[src],
                )
            if tgt not in nodes:
                raise DAGValidationError(
                    message=f"Dependency edge references non-existent target node '{tgt}'",
                    error_code="MISSING_TARGET_NODE",
                    violating_nodes=[tgt],
                )

            # 6. Duplicate edge check
            if (src, tgt) in seen_edges:
                continue  # Idempotently ignore duplicate identical edges
            seen_edges.add((src, tgt))

            in_edges[tgt].add(src)
            out_edges[src].add(tgt)

        # 7. Max fan-out check
        for src, targets in out_edges.items():
            if len(targets) > self.max_fan_out:
                raise DAGValidationError(
                    message=f"Node '{src}' exceeds maximum fan-out limit ({len(targets)} > {self.max_fan_out})",
                    error_code="MAX_FAN_OUT_EXCEEDED",
                    violating_nodes=[src],
                )

        # 8. Cycle Detection & Deterministic Topological Sort (Kahn's Algorithm)
        in_degrees: dict[str, int] = {
            nid: len(parents) for nid, parents in in_edges.items()
        }
        # Deterministic queue: sort initially available root nodes alphabetically
        zero_in_degree = sorted([nid for nid, deg in in_degrees.items() if deg == 0])

        topological_order: list[str] = []
        depth_map: dict[str, int] = dict.fromkeys(zero_in_degree, 1)

        queue = deque(zero_in_degree)

        while queue:
            # Deterministic pop
            curr = queue.popleft()
            topological_order.append(curr)

            # Deterministically visit children
            for child in sorted(out_edges[curr]):
                # Compute critical path depth
                child_depth = depth_map[curr] + 1
                if child not in depth_map or child_depth > depth_map[child]:
                    depth_map[child] = child_depth

                in_degrees[child] -= 1
                if in_degrees[child] == 0:
                    queue.append(child)

        # Cycle check: if topological order does not contain all nodes, a cycle exists
        if len(topological_order) != len(nodes):
            cyclic_nodes = sorted([nid for nid, deg in in_degrees.items() if deg > 0])
            raise DAGValidationError(
                message=f"Cycle detected in research plan involving nodes: {cyclic_nodes}",
                error_code="CYCLE_DETECTED",
                violating_nodes=cyclic_nodes,
            )

        # 9. Max Depth (Critical Path) Check
        max_depth = max(depth_map.values()) if depth_map else 0
        if max_depth > self.max_depth:
            raise DAGValidationError(
                message=f"Plan critical path depth ({max_depth}) exceeds maximum limit ({self.max_depth})",
                error_code="MAX_DEPTH_EXCEEDED",
                violating_nodes=topological_order,
            )

        root_nodes = tuple(
            sorted([nid for nid, parents in in_edges.items() if not parents])
        )
        leaf_nodes = tuple(
            sorted([nid for nid, children in out_edges.items() if not children])
        )
        max_fan_out = max((len(targets) for targets in out_edges.values()), default=0)

        metrics = DAGMetrics(
            node_count=len(nodes),
            edge_count=len(seen_edges),
            critical_path_depth=max_depth,
            max_fan_out=max_fan_out,
            root_node_ids=root_nodes,
            leaf_node_ids=leaf_nodes,
        )

        return ValidatedDAG(
            plan_id=plan.plan_id,
            run_id=plan.run_id,
            topological_order=tuple(topological_order),
            metrics=metrics,
            node_dependencies={
                nid: tuple(sorted(parents)) for nid, parents in in_edges.items()
            },
            node_dependents={
                nid: tuple(sorted(children)) for nid, children in out_edges.items()
            },
        )
