"""A scenario file (batch 7, CHG-010a): `evals/scenarios/<name>/expected.yaml`.

It names the TDD scenario, the steps that play it (the clock, mail, uploads
and the owner's own actions, through the same code the web app calls), and
the expectations that decide it. Each expectation is one SQL query against
the run's database, tagged with the component that owns the outcome, so a
failed run names the stage that broke. Inputs are the shared fixtures (or a
file in the scenario's own folder); replies live only in
fixtures/ai_replies.json."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCENARIOS = Path(__file__).resolve().parent / "scenarios"
# Pipeline order: when several fail, the earliest names the broken component.
COMPONENTS = ("sort", "extract", "validate", "reconcile", "planner", "agent")
Component = Literal["sort", "extract", "validate", "reconcile", "planner", "agent"]
STEP_KINDS = {"at", "deliver", "poll", "drain", "monday_plan", "approve", "upload", "confirm_waiting", "unlock",
              "confirm_balance", "choose_option"}


class Expectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    component: Component
    sql: str
    equals: Any = None
    rows: list[list[Any]] | None = None
    why: str = ""  # what it shows, for the report

    @model_validator(mode="after")
    def _one_check(self) -> Expectation:
        if (self.rows is None) == ("equals" not in self.model_fields_set):
            raise ValueError(f"expectation {self.id}: give exactly one of equals or rows")
        if not self.sql.lstrip().upper().startswith("SELECT"):
            raise ValueError(f"expectation {self.id}: a check is a SELECT")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    title: str  # the TDD's scenario name
    passes_when: str  # the TDD's "passes when"
    steps: list[dict[str, Any]] = Field(min_length=1)
    expect: list[Expectation] = Field(min_length=1)
    folder: Path | None = None

    @model_validator(mode="after")
    def _known_steps(self) -> Scenario:
        for step in self.steps:
            if len(step) != 1 or next(iter(step)) not in STEP_KINDS:
                raise ValueError(f"{self.name}: a step is one of {sorted(STEP_KINDS)}, got {step}")
        return self


def load(name: str) -> Scenario:
    folder = SCENARIOS / name
    raw = yaml.safe_load((folder / "expected.yaml").read_text(encoding="utf-8"))
    return Scenario.model_validate({**raw, "folder": folder})


def names() -> list[str]:
    return sorted(p.parent.name for p in SCENARIOS.glob("*/expected.yaml"))
