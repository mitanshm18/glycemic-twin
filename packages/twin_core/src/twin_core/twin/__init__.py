"""The Digital Twin core (M4): versioned, deterministic per-person state built from observations
up to ``as_of``, served with the frozen M3 model contract. Pure Python; no web, database or UI code.

    from twin_core.twin import TwinConfigs, TwinRuntime, InMemorySource, build_state, simulate
"""

from twin_core.twin.config import TwinConfig, TwinConfigs, load_twin_config
from twin_core.twin.diff import StateDiff, diff_states
from twin_core.twin.engine import FutureDataError, TwinRuntime, build_state
from twin_core.twin.model import ModelContractError, ModelIdentity, RiskModel, check_compatible
from twin_core.twin.record import InMemorySource, PatientRecord, RecordSource
from twin_core.twin.state import DISCLAIMER, ENGINE_VERSION, STATE_SCHEMA, Phase, TwinState
from twin_core.twin.support import SupportProfile, build_support_profile
from twin_core.twin.whatif import ScenarioError, ScenarioResult, simulate

__all__ = [
    "DISCLAIMER",
    "ENGINE_VERSION",
    "STATE_SCHEMA",
    "FutureDataError",
    "InMemorySource",
    "ModelContractError",
    "ModelIdentity",
    "PatientRecord",
    "Phase",
    "RecordSource",
    "RiskModel",
    "ScenarioError",
    "ScenarioResult",
    "StateDiff",
    "SupportProfile",
    "TwinConfig",
    "TwinConfigs",
    "TwinRuntime",
    "TwinState",
    "build_state",
    "build_support_profile",
    "check_compatible",
    "diff_states",
    "load_twin_config",
    "simulate",
]
