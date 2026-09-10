"""Deterministic mission families for later GTASTL integration.

The module deliberately has no Pygame dependency. A game loop can construct a
mission, call ``start()``, forward named gameplay events through ``on_event()``,
and advance frame-based clocks with ``tick()``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


OFFERED = "offered"
ACTIVE = "active"
SUCCEEDED = "succeeded"
FAILED = "failed"
TERMINAL_STATUSES = frozenset((SUCCEEDED, FAILED))

VEHICLE_THEFT = "vehicle_theft"
SMASH_TARGETS = "smash_targets"
EVADE_HEAT = "evade_heat"
MISSION_FAMILIES = (VEHICLE_THEFT, SMASH_TARGETS, EVADE_HEAT)


@dataclass(frozen=True)
class MissionUpdate:
    """One immutable result suitable for HUD, audio, and economy hooks."""

    family: str
    name: str
    status: str
    stage: str
    objective: str
    progress: int
    target: int
    steps_left: int
    reward_delta: int = 0
    message: str = ""

    @property
    def complete(self) -> bool:
        return self.status == SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.status == FAILED

    @property
    def progress_ratio(self) -> float:
        if self.target <= 0:
            return 1.0 if self.complete else 0.0
        return min(1.0, max(0.0, self.progress / float(self.target)))

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Mission:
    """Base lifecycle shared by all mission families."""

    family = "mission"

    def __init__(self, name: str, objective: str, reward: int,
                 time_limit_steps: int) -> None:
        if not name or not objective:
            raise ValueError("missions need a name and objective")
        if reward < 0:
            raise ValueError("reward cannot be negative")
        if time_limit_steps <= 0:
            raise ValueError("time limit must be positive")
        self.name = name
        self.status = OFFERED
        self.stage = "offered"
        self.objective = objective
        self.reward = int(reward)
        self.time_limit_steps = int(time_limit_steps)
        self.steps_left = int(time_limit_steps)
        self.progress = 0
        self.target = 1
        self.message = ""

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def snapshot(self, reward_delta: int = 0,
                 message: Optional[str] = None) -> MissionUpdate:
        return MissionUpdate(
            family=self.family,
            name=self.name,
            status=self.status,
            stage=self.stage,
            objective=self.objective,
            progress=self.progress,
            target=self.target,
            steps_left=max(0, self.steps_left),
            reward_delta=int(reward_delta),
            message=self.message if message is None else message,
        )

    def start(self) -> MissionUpdate:
        if self.status != OFFERED:
            return self.snapshot()
        self.status = ACTIVE
        self.stage = self.initial_stage
        self.message = self.start_message
        return self.snapshot(message=self.message)

    @property
    def initial_stage(self) -> str:
        return "active"

    @property
    def start_message(self) -> str:
        return self.name.upper()

    def tick(self, steps: int = 1, **world: Any) -> MissionUpdate:
        steps = self._validated_steps(steps)
        if not self.is_active or steps == 0:
            return self.snapshot()
        update = self._tick_world(steps, **world)
        if update is not None or not self.is_active:
            return update if update is not None else self.snapshot()
        self.steps_left = max(0, self.steps_left - steps)
        if self.steps_left == 0:
            return self._fail("TIME RAN OUT")
        return self.snapshot()

    def on_event(self, event: str, **data: Any) -> MissionUpdate:
        if not self.is_active:
            return self.snapshot()
        if event in ("player_busted", "player_wasted"):
            return self._fail("BUSTED" if event == "player_busted" else "WASTED")
        return self._on_event(event, **data)

    def _tick_world(self, steps: int, **world: Any) -> Optional[MissionUpdate]:
        return None

    def _on_event(self, event: str, **data: Any) -> MissionUpdate:
        return self.snapshot()

    def _succeed(self, message: str, reward: Optional[int] = None) -> MissionUpdate:
        if not self.is_active:
            return self.snapshot()
        payout = self.reward if reward is None else max(0, int(reward))
        self.status = SUCCEEDED
        self.stage = "complete"
        self.progress = self.target
        self.message = message
        return self.snapshot(reward_delta=payout, message=message)

    def _fail(self, message: str) -> MissionUpdate:
        if not self.is_active:
            return self.snapshot()
        self.status = FAILED
        self.stage = "failed"
        self.message = message
        return self.snapshot(message=message)

    @staticmethod
    def _validated_steps(steps: int) -> int:
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 0:
            raise ValueError("steps must be a non-negative integer")
        return steps


class VehicleTheftMission(Mission):
    """Steal one marked vehicle and deliver it intact to a chop shop."""

    family = VEHICLE_THEFT

    def __init__(self, target_vehicle_id: Any, vehicle_name: str,
                 chop_shop_id: Any = "kingshighway_shop", *, reward: int = 900,
                 time_limit_steps: int = 60 * 75,
                 name: str = "Kingshighway Reclamation") -> None:
        if target_vehicle_id is None or chop_shop_id is None:
            raise ValueError("vehicle and chop-shop ids are required")
        self.target_vehicle_id = target_vehicle_id
        self.vehicle_name = vehicle_name
        self.chop_shop_id = chop_shop_id
        super().__init__(
            name,
            f"Lift the marked {vehicle_name}; deliver it intact to Kingshighway.",
            reward,
            time_limit_steps,
        )
        self.target = 2

    @property
    def initial_stage(self) -> str:
        return "steal"

    def _on_event(self, event: str, **data: Any) -> MissionUpdate:
        vehicle_id = data.get("vehicle_id")
        if event == "vehicle_destroyed" and vehicle_id == self.target_vehicle_id:
            return self._fail("THE MARKED RIDE IS SCRAP")
        if event == "vehicle_entered" and vehicle_id == self.target_vehicle_id:
            self.stage = "deliver"
            self.progress = 1
            self.objective = "Take the marked ride to the Kingshighway chop shop."
            self.message = "RIDE ACQUIRED"
            return self.snapshot(message=self.message)
        if (event == "vehicle_exited" and vehicle_id == self.target_vehicle_id
                and self.progress == 1):
            self.stage = "recover"
            self.objective = f"Get back in the marked {self.vehicle_name}."
            self.message = "DON'T LEAVE THE RIDE"
            return self.snapshot(message=self.message)
        if event == "location_reached" and data.get("location_id") == self.chop_shop_id:
            if vehicle_id != self.target_vehicle_id or self.progress < 1:
                return self.snapshot()
            condition = min(1.0, max(0.0, float(data.get("condition", 1.0))))
            payout = int(round(self.reward * (0.5 + 0.5 * condition)))
            return self._succeed("DELIVERED CLEAN ENOUGH", payout)
        return self.snapshot()


class SmashTargetsMission(Mission):
    """Destroy a fixed set of marked property targets before the deadline."""

    family = SMASH_TARGETS

    def __init__(self, target_ids: Iterable[Any], *, reward: int = 1400,
                 time_limit_steps: int = 60 * 60,
                 name: str = "Grand Avenue Glass Run") -> None:
        ordered = tuple(target_ids)
        if not ordered or len(set(ordered)) != len(ordered):
            raise ValueError("smash targets must be non-empty and unique")
        self.target_ids: Tuple[Any, ...] = ordered
        self.smashed = set()
        super().__init__(
            name,
            f"Smash {len(ordered)} marked targets before the sirens close in.",
            reward,
            time_limit_steps,
        )
        self.target = len(ordered)

    @property
    def initial_stage(self) -> str:
        return "rampage"

    def _on_event(self, event: str, **data: Any) -> MissionUpdate:
        if event != "target_smashed":
            return self.snapshot()
        target_id = data.get("target_id")
        if target_id not in self.target_ids or target_id in self.smashed:
            return self.snapshot()
        self.smashed.add(target_id)
        self.progress = len(self.smashed)
        if self.progress == self.target:
            return self._succeed("GRAND AVENUE IS IN PIECES")
        remaining = self.target - self.progress
        self.objective = f"Smash {remaining} more marked target{'s' if remaining != 1 else ''}."
        self.message = f"{self.progress}/{self.target} SMASHED"
        return self.snapshot(message=self.message)


class EvadeHeatMission(Mission):
    """Lose the police, remain unseen, then reach a named safehouse."""

    family = EVADE_HEAT

    def __init__(self, safehouse_id: Any = "the_hill_safehouse", *,
                 cool_steps: int = 60 * 8, reward: int = 1800,
                 time_limit_steps: int = 60 * 90,
                 name: str = "Take Forty") -> None:
        if safehouse_id is None:
            raise ValueError("safehouse id is required")
        if cool_steps <= 0:
            raise ValueError("cool-down must be positive")
        self.safehouse_id = safehouse_id
        self.cool_steps = int(cool_steps)
        self.clean_steps = 0
        super().__init__(
            name,
            "Break police sightlines, lose the heat, then make The Hill.",
            reward,
            time_limit_steps,
        )
        self.target = self.cool_steps

    @property
    def initial_stage(self) -> str:
        return "break_contact"

    def _tick_world(self, steps: int, **world: Any) -> Optional[MissionUpdate]:
        if "wanted_level" not in world or "spotted" not in world:
            raise ValueError("getaway ticks need wanted_level and spotted")
        wanted_level = max(0, int(world["wanted_level"]))
        spotted = bool(world["spotted"])
        if wanted_level > 0 or spotted:
            self.clean_steps = 0
            self.progress = 0
            self.stage = "break_contact"
            self.objective = "Break police sightlines and lose every wanted star."
            return None
        if self.stage != "reach_safehouse":
            self.stage = "lay_low"
            self.clean_steps = min(self.cool_steps, self.clean_steps + steps)
            self.progress = self.clean_steps
            remain = max(0, self.cool_steps - self.clean_steps)
            self.objective = f"Stay unseen for {remain} more step{'s' if remain != 1 else ''}."
            if self.clean_steps >= self.cool_steps:
                self.stage = "reach_safehouse"
                self.objective = "Heat is gone. Reach the safehouse on The Hill."
                self.message = "YOU LOST THEM"
        return None

    def _on_event(self, event: str, **data: Any) -> MissionUpdate:
        if (event == "location_reached" and self.stage == "reach_safehouse"
                and data.get("location_id") == self.safehouse_id):
            return self._succeed("MADE IT TO THE HILL")
        return self.snapshot()


def create_mission(family: str, **kwargs: Any) -> Mission:
    """Construct a mission by stable family id for save files or dispatchers."""

    builders = {
        VEHICLE_THEFT: VehicleTheftMission,
        SMASH_TARGETS: SmashTargetsMission,
        EVADE_HEAT: EvadeHeatMission,
    }
    try:
        builder = builders[family]
    except KeyError as exc:
        raise ValueError(f"unknown mission family: {family}") from exc
    return builder(**kwargs)


__all__ = [
    "ACTIVE", "EVADE_HEAT", "FAILED", "MISSION_FAMILIES", "Mission",
    "MissionUpdate", "OFFERED", "SMASH_TARGETS", "SUCCEEDED",
    "TERMINAL_STATUSES", "VEHICLE_THEFT", "EvadeHeatMission",
    "SmashTargetsMission", "VehicleTheftMission", "create_mission",
]
