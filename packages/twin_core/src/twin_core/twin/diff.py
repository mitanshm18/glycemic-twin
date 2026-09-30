"""Explain what changed between two twin states of the same person."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from twin_core.twin.state import TwinState

# Identity/bookkeeping fields that change whenever anything changes; not explanations in themselves.
IGNORED = ("state_id", "provenance.record_sha256", "provenance.max_source_ts")


class Change(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    before: Any
    after: Any


class StateDiff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_state_id: str
    to_state_id: str
    from_as_of: str
    to_as_of: str
    explanations: list[str]
    changes: list[Change]


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix: obj}


def diff_states(a: TwinState, b: TwinState) -> StateDiff:
    if a.patient_id != b.patient_id:
        raise ValueError("states belong to different patients")
    fa, fb = _flatten(a.model_dump(mode="json")), _flatten(b.model_dump(mode="json"))
    changes = [
        Change(path=k, before=fa.get(k), after=fb.get(k))
        for k in sorted(set(fa) | set(fb))
        if fa.get(k) != fb.get(k) and not k.startswith(IGNORED)
    ]
    why: list[str] = []
    new_closed = [
        m for m in b.provenance.closed_meal_ids_used if m not in a.provenance.closed_meal_ids_used
    ]
    if new_closed:
        why.append(
            f"{len(new_closed)} meal window(s) closed and became personal evidence: {', '.join(new_closed)}"
        )
    if a.lifecycle.phase != b.lifecycle.phase:
        why.append(
            f"lifecycle {a.lifecycle.phase.value} -> {b.lifecycle.phase.value}: {b.lifecycle.reason}"
        )
    ra, rb = a.personal_response, b.personal_response
    if ra and rb and (ra.p_personal != rb.p_personal or ra.personal_weight != rb.personal_weight):
        why.append(
            f"personal rate {ra.p_personal:.3f} -> {rb.p_personal:.3f}, weight "
            f"{ra.personal_weight:.2f} -> {rb.personal_weight:.2f}"
        )
    ma = a.current_meal.meal_id if a.current_meal else None
    mb = b.current_meal.meal_id if b.current_meal else None
    if ma != mb or (a.current_meal is None) != (b.current_meal is None):
        why.append(f"current meal {ma or 'none'} -> {mb or 'none'}")
    if a.risk.probability != b.risk.probability:
        why.append(
            f"risk {a.risk.status}:{a.risk.probability} -> {b.risk.status}:{b.risk.probability}"
        )
    if a.current_physiology.glucose_mgdl != b.current_physiology.glucose_mgdl:
        why.append(
            f"latest glucose {a.current_physiology.glucose_mgdl} -> {b.current_physiology.glucose_mgdl} mg/dL"
        )
    if a.provenance.model != b.provenance.model:
        why.append("a different model version produced the risk")
    return StateDiff(
        from_state_id=a.state_id,
        to_state_id=b.state_id,
        from_as_of=a.as_of,
        to_as_of=b.as_of,
        explanations=why,
        changes=changes,
    )
