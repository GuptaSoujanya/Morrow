"""A record of how each model-assisted step was researched, verified, checked and executed.

Every step the audit takes with a model goes through the same four moves, and
each move leaves a sentence here so the report can show the reader exactly what
was looked up, what was verified before the model was asked, how the answer was
checked for accuracy, and what was finally done with it. A step that fails its
check is kept with ok=False and its result is not applied.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class Step:
    name: str
    research: str
    verify: str
    check: str
    execute: str
    ok: bool = True
    numbers: Dict[str, Any] = field(default_factory=dict)


class Trail:
    def __init__(self) -> None:
        self.steps: List[Step] = []

    def add(self, name: str, *, research: str, verify: str, check: str, execute: str, ok: bool = True,
            **numbers: Any) -> Step:
        step = Step(name, research, verify, check, execute, ok, dict(numbers))
        self.steps.append(step)
        return step

    def as_dicts(self) -> List[Dict[str, Any]]:
        return [asdict(step) for step in self.steps]

    def failed(self) -> List[Step]:
        return [step for step in self.steps if not step.ok]
