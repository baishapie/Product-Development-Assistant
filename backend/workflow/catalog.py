"""Declarative stage catalog for product-document workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageSpec:
    """A business stage and the graph node that executes it."""

    stage_id: str
    node: str
    depends_on: tuple[str, ...] = ()
    gate_node: str | None = None
    required: bool = True


@dataclass(frozen=True)
class WorkflowPlan:
    """An immutable, topologically ordered workflow plan."""

    name: str
    stages: tuple[StageSpec, ...]

    def __post_init__(self) -> None:
        ids = [stage.stage_id for stage in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate stage in plan {self.name!r}")
        known = set(ids)
        seen: set[str] = set()
        for stage in self.stages:
            missing = set(stage.depends_on) - known
            if missing:
                raise ValueError(f"{stage.stage_id!r} has unknown dependencies: {sorted(missing)}")
            if not set(stage.depends_on) <= seen:
                raise ValueError(
                    f"plan {self.name!r} is not topologically ordered at {stage.stage_id!r}"
                )
            seen.add(stage.stage_id)

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.stages if stage.required)

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(stage.node for stage in self.stages if stage.required))

    @property
    def gate_ids(self) -> tuple[str, ...]:
        return tuple(
            stage.gate_node
            for stage in self.stages
            if stage.required and stage.gate_node is not None
        )

    def get(self, stage_id: str) -> StageSpec | None:
        return next((stage for stage in self.stages if stage.stage_id == stage_id), None)

    def require(self, stage_id: str) -> StageSpec:
        stage = self.get(stage_id)
        if stage is None or not stage.required:
            raise ValueError(f"stage {stage_id!r} is not enabled in plan {self.name!r}")
        return stage


MVP_PLAN = WorkflowPlan(
    name="mvp",
    stages=(
        StageSpec("product", "product", gate_node="review_product"),
        StageSpec("architect", "architect", depends_on=("product",), gate_node="review_architect"),
    ),
)

FULL_PLAN = WorkflowPlan(
    name="full",
    stages=(
        StageSpec("product", "product", gate_node="review_product"),
        StageSpec("architect", "architect", depends_on=("product",), gate_node="review_architect"),
        StageSpec("backend", "backend", depends_on=("architect",)),
        StageSpec("frontend", "frontend", depends_on=("architect",)),
        StageSpec("qa", "qa", depends_on=("backend", "frontend")),
    ),
)

PLANS = {MVP_PLAN.name: MVP_PLAN, FULL_PLAN.name: FULL_PLAN}


def get_plan(name: str) -> WorkflowPlan:
    """Return the explicitly requested plan; unknown values fail closed."""
    try:
        return PLANS[name.strip().lower()]
    except (AttributeError, KeyError):
        raise ValueError(f"unknown workflow plan: {name!r}") from None
