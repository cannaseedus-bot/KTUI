"""Decision closure under unknown probabilities: a choice can be made without inventing a likelihood.

Two invariants from the review, both enforced here rather than documented:

    UNKNOWN(P(b)) != 0.5        an unresolved probability stays unresolved; nothing substitutes a prior
    Xul(Action) !=> Xul(Fact)   closing an action never closes the uncertainty it was decided under

The typed contract:

    {"schema": "kuhul-decision/v1", "id": ..., "policy": "minimax",
     "selected_action": "skip", "expected_utility": None,
     "action_collapsed": True, "fact_collapsed": False,
     "authority": "proposal", "execution": False}

`action_collapsed: true` means **a choice was selected**, not that it was executed. Execution remains
an XCFE admission decision, and the facts the choice was made under stay unresolved.

Policies are typed, not blended: `expected_utility` requires every probability of every action to be
known, and refuses rather than falling back; `minimax` needs only utilities, so it can decide while the
probabilities remain UNKNOWN.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

SCHEMA = "kuhul-decision/v1"
POLICIES = ("expected_utility", "minimax", "maximin")
UNKNOWN_WORDS = ("unknown", "unresolved", "none", "", "null", "?")


class DecisionError(ValueError):
    """A decision that cannot be evaluated as declared."""


def probability_type(value) -> str:
    """`known` or `unknown`. A string like "UNKNOWN" is unknown; 0.0 and 1.0 are known."""
    if value is None:
        return "unknown"
    if isinstance(value, str):
        return "unknown" if value.strip().lower() in UNKNOWN_WORDS else (
            "known" if _is_probability(value) else "invalid")
    return "known" if _is_probability(value) else "invalid"


def _is_probability(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and 0.0 <= number <= 1.0


@dataclass
class Branch:
    action: str
    branch: str
    utility: float
    probability: object = None      # None means UNKNOWN - never 0.5

    def probability_kind(self) -> str:
        return probability_type(self.probability)


@dataclass
class Decision:
    identifier: str
    policy: str
    branches: list[Branch] = field(default_factory=list)

    def actions(self) -> list[str]:
        seen: list[str] = []
        for branch in self.branches:
            if branch.action not in seen:
                seen.append(branch.action)
        return seen

    def _action_branches(self, action: str) -> list[Branch]:
        return [branch for branch in self.branches if branch.action == action]

    def expected_utility(self, action: str) -> float | None:
        """Only defined when every probability of the action is known. No substitution, no default."""
        branches = self._action_branches(action)
        if not branches:
            raise DecisionError(f"unknown action {action!r}")
        for branch in branches:
            if branch.probability_kind() == "invalid":
                raise DecisionError(f"probability {branch.probability!r} is not in [0, 1]")
        if any(branch.probability_kind() == "unknown" for branch in branches):
            return None
        total = sum(float(branch.probability) for branch in branches)
        if abs(total - 1.0) > 1e-9:
            raise DecisionError(f"probabilities for {action!r} sum to {total:g}, not 1")
        return round(sum(float(branch.probability) * branch.utility for branch in branches), 6)

    def worst_case(self, action: str) -> float:
        """Minimax needs utilities only - which is why it can decide under UNKNOWN probabilities."""
        branches = self._action_branches(action)
        if not branches:
            raise DecisionError(f"unknown action {action!r}")
        return min(branch.utility for branch in branches)

    def evaluate(self) -> dict:
        """Run the declared policy. A tie is broken deterministically and reported."""
        if self.policy not in POLICIES:
            raise DecisionError(f"unknown policy {self.policy!r}")
        actions = self.actions()
        if not actions:
            raise DecisionError("a decision needs at least one action")
        utilities = {action: self.expected_utility(action) for action in actions}
        worst = {action: self.worst_case(action) for action in actions}
        unknown = [action for action in actions if utilities[action] is None]

        if self.policy == "expected_utility":
            if unknown:
                return self._result(selected=None, metric=None, utilities=utilities, worst=worst,
                                    refused="probabilities_unknown", unresolved=unknown)
            ranked = sorted(actions, key=lambda action: (-utilities[action], action))
            best = utilities[ranked[0]]
            ties = [action for action in ranked
                    if abs(utilities[action] - best) <= 1e-9]
            ties = ties if len(ties) > 1 else []
            return self._result(selected=ranked[0], metric=best, utilities=utilities, worst=worst,
                                ties=ties)

        # minimax / maximin: maximise the worst case. Utilities only, so UNKNOWN is no obstacle.
        ranked = sorted(actions, key=lambda action: (-worst[action], action))
        best = worst[ranked[0]]
        ties = [action for action in ranked if abs(worst[action] - best) <= 1e-9]
        ties = ties if len(ties) > 1 else []
        return self._result(selected=ranked[0], metric=best, utilities=utilities, worst=worst,
                            ties=ties)

    def _result(self, *, selected, metric, utilities, worst, ties=None, refused=None,
                unresolved=None) -> dict:
        return dict(schema=SCHEMA, id=self.identifier, policy=self.policy,
                    selected_action=selected,
                    metric=None if metric is None else round(float(metric), 6),
                    expected_utility=None if selected is None else utilities[selected],
                    worst_case={action: value for action, value in worst.items()},
                    expected_utilities={action: value for action, value in utilities.items()},
                    unresolved_actions=unresolved or [],
                    ties=ties or [],
                    refused=refused,
                    action_collapsed=selected is not None,
                    fact_collapsed=False,
                    authority="proposal", execution=False, mutation=False,
                    note=("a choice was selected; nothing was executed and no fact was closed"
                          if selected is not None else
                          "the policy could not close an action under the supplied information"))


def decide(identifier: str, branches: list[dict], *, policy: str = "minimax") -> dict:
    """Evaluate a decision from `{action, branch, utility, probability}` records."""
    records: list[Branch] = []
    for index, item in enumerate(branches or []):
        if not isinstance(item, dict):
            raise DecisionError(f"branch #{index} is not an object")
        action = str(item.get("action") or "")
        if not action:
            raise DecisionError(f"branch #{index} has no action")
        utility = item.get("utility")
        if not isinstance(utility, (int, float)) or isinstance(utility, bool) \
                or not math.isfinite(float(utility)):
            raise DecisionError(f"branch #{index} utility {utility!r} is not a finite number")
        records.append(Branch(action=action, branch=str(item.get("branch") or f"#{index}"),
                              utility=float(utility), probability=item.get("probability")))
    return Decision(identifier=identifier, policy=policy, branches=records).evaluate()


# -- closure -------------------------------------------------------------------------------------------
def close_action(decision: dict) -> dict:
    """Xul(action): the choice is selected. The facts it was made under remain unresolved."""
    if decision.get("selected_action") is None:
        raise DecisionError("no action was selected; there is nothing to close")
    return dict(decision, action_collapsed=True, fact_collapsed=False,
                closure="action", authority="proposal", execution=False)


def close_fact(decision: dict, *, verdict: str, evidence: str = "") -> dict:
    """Xul(fact) requires its own verdict. Closing an action never implies it."""
    if str(verdict or "").upper() not in ("PASS", "FAIL"):
        raise DecisionError(f"a fact closes only on PASS or FAIL, not {verdict!r}")
    return dict(decision, fact_collapsed=True, fact_verdict=str(verdict).upper(),
                fact_evidence=evidence, closure="fact")


def summary(result: dict) -> str:
    lines = [f"decision {result['id']!r} · policy {result['policy']}",
             f"  selected: {result['selected_action'] or '(none)'}"
             f" · metric: {result['metric']}"
             f" · expected_utility: {result['expected_utility']}",
             f"  worst case: {result['worst_case']}",
             f"  action_collapsed: {result['action_collapsed']}"
             f" · fact_collapsed: {result['fact_collapsed']}",
             f"  authority: {result['authority']} · execution: {result['execution']}"]
    if result["unresolved_actions"]:
        lines.append(f"  unresolved probabilities for: {', '.join(result['unresolved_actions'])}")
    if result["ties"]:
        lines.append(f"  tie between: {', '.join(result['ties'])} (broken by name)")
    if result["refused"]:
        lines.append(f"  refused: {result['refused']}")
    return "\n".join(lines)
