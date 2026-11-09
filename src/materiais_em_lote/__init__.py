"""Planejamento local de materiais com quantidades racionais exatas."""

__version__ = "1.0.0"

from .core import (  # noqa: E402
    PlanError, Project, Plan, parse_project, validate_project, plan_project,
    quantity_text,
)
from .demo import demo_mapping, demo_project  # noqa: E402
from .reports import build_bundle, publish_bundle  # noqa: E402

__all__ = [
    "PlanError", "Project", "Plan", "parse_project", "validate_project",
    "plan_project", "quantity_text", "demo_mapping", "demo_project",
    "build_bundle", "publish_bundle", "__version__",
]
