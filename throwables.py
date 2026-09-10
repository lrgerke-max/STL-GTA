"""Deterministic, renderer-agnostic throwable gameplay for GTASTL.

Time is measured in 60 Hz simulation steps to match ``main.py``.  The module
intentionally has no pygame dependency: integration supplies target snapshots
and an optional collision callback, then consumes immutable gameplay events.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Hashable, Iterable, Mapping, Optional


SIM_HZ = 60
TIMED_EXPLOSIVE = "timed_explosive"
FIRE_BOTTLE = "fire_bottle"
THROWABLE_ORDER = (TIMED_EXPLOSIVE, FIRE_BOTTLE)

Vec2 = tuple[float, float]
CollisionQuery = Callable[[Vec2, Vec2], bool]


@dataclass(frozen=True)
class ThrowableSpec:
    label: str
    inventory_limit: int
    cooldown_steps: int
    throw_speed: float
    lift_speed: float
    gravity: float
    fuse_steps: int
    bounce: float = 0.0
    ground_friction: float = 0.0
    blast_radius: float = 0.0
    max_damage: float = 0.0
    edge_damage: float = 0.0
    fire_radius: float = 0.0
    fire_steps: int = 0
    fire_tick_steps: int = 0
    fire_damage: float = 0.0
    burn_status_steps: int = 0


THROWABLE_SPECS: Mapping[str, ThrowableSpec] = {
    TIMED_EXPLOSIVE: ThrowableSpec(
        label="TIMED EXPLOSIVE",
        inventory_limit=8,
        cooldown_steps=42,
        throw_speed=7.4,
        lift_speed=3.8,
        gravity=0.17,
        fuse_steps=90,
        bounce=0.42,
        ground_friction=0.58,
        blast_radius=108.0,
        max_damage=125.0,
        edge_damage=18.0,
    ),
    FIRE_BOTTLE: ThrowableSpec(
        label="FIRE BOTTLE",
        inventory_limit=6,
        cooldown_steps=30,
        throw_speed=6.4,
        lift_speed=3.25,
        gravity=0.18,
        fuse_steps=96,  # airborne failsafe; ordinary ignition is on impact
        fire_radius=62.0,
        fire_steps=SIM_HZ * 6,
        fire_tick_steps=15,
        fire_damage=9.0,
        burn_status_steps=SIM_HZ * 2,
    ),
}


@dataclass(frozen=True)
class TargetSnapshot:
    target_id: Hashable
    position: Vec2
    radius: float = 0.0
    blast_multiplier: float = 1.0
    fire_multiplier: float = 1.0


@dataclass(frozen=True)
class DamageEvent:
    target_id: Hashable
    source_projectile_id: int
    owner_id: Optional[Hashable]
    cause: str
    damage: float
    impulse: Vec2
    status: Optional[str] = None
    status_steps: int = 0


@dataclass(frozen=True)
class BlastEvent:
    projectile_id: int
    owner_id: Optional[Hashable]
    center: Vec2
    radius: float
    max_damage: float
    edge_damage: float

    def damage_at(self, position: Vec2, target_radius: float = 0.0) -> float:
        """Return linear radial damage, accounting for a target's footprint."""
        distance = max(0.0, _distance(self.center, position) - max(0.0, target_radius))
        if distance > self.radius:
            return 0.0
        ratio = distance / self.radius
        return self.max_damage + (self.edge_damage - self.max_damage) * ratio


@dataclass(frozen=True)
class ImpactEvent:
    projectile_id: int
    kind: str
    position: Vec2
    surface: str


@dataclass(frozen=True)
class FireStartedEvent:
    zone_id: int
    projectile_id: int
    owner_id: Optional[Hashable]
    center: Vec2
    radius: float
    duration_steps: int


@dataclass(frozen=True)
class ProjectileView:
    projectile_id: int
    kind: str
    owner_id: Optional[Hashable]
    position: Vec2
    velocity: Vec2
    height: float
    vertical_velocity: float
    fuse_remaining: int
    bounce_count: int
    grounded: bool


@dataclass(frozen=True)
class FireZoneView:
    zone_id: int
    source_projectile_id: int
    owner_id: Optional[Hashable]
    center: Vec2
    radius: float
    remaining_steps: int
    next_damage_in: int


@dataclass(frozen=True)
class ThrowResult:
    success: bool
    reason: str
    projectile: Optional[ProjectileView] = None


@dataclass(frozen=True)
class UpdateEvents:
    impacts: tuple[ImpactEvent, ...] = ()
    blasts: tuple[BlastEvent, ...] = ()
    fires_started: tuple[FireStartedEvent, ...] = ()
    damage: tuple[DamageEvent, ...] = ()
    fires_expired: tuple[int, ...] = ()


@dataclass
class _Projectile:
    projectile_id: int
    kind: str
    owner_id: Optional[Hashable]
    x: float
    y: float
    vx: float
    vy: float
    height: float
    vz: float
    fuse_remaining: int
    bounce_count: int = 0
    grounded: bool = False


@dataclass
class _FireZone:
    zone_id: int
    source_projectile_id: int
    owner_id: Optional[Hashable]
    x: float
    y: float
    remaining_steps: int
    next_damage_in: int


def _distance(a: Vec2, b: Vec2) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _direction_and_distance(origin: Vec2, target: Vec2) -> tuple[Vec2, float]:
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-9:
        return (1.0, 0.0), 0.0
    return (dx / distance, dy / distance), distance


def damage_from_blast(blast: BlastEvent,
                      targets: Iterable[TargetSnapshot]) -> tuple[DamageEvent, ...]:
    """Side-effect-free target query for one radial explosion."""
    events = []
    for target in targets:
        damage = blast.damage_at(target.position, target.radius)
        if damage <= 0.0 or target.blast_multiplier <= 0.0:
            continue
        direction, distance = _direction_and_distance(blast.center, target.position)
        strength = max(0.18, 1.0 - distance / blast.radius)
        events.append(DamageEvent(
            target_id=target.target_id,
            source_projectile_id=blast.projectile_id,
            owner_id=blast.owner_id,
            cause="blast",
            damage=damage * target.blast_multiplier,
            impulse=(direction[0] * 9.0 * strength,
                     direction[1] * 9.0 * strength),
            status="staggered",
            status_steps=max(6, round(30 * strength)),
        ))
    return tuple(events)


def damage_from_fire(zone: FireZoneView,
                     targets: Iterable[TargetSnapshot]) -> tuple[DamageEvent, ...]:
    """Side-effect-free target query for one fire damage pulse."""
    spec = THROWABLE_SPECS[FIRE_BOTTLE]
    events = []
    for target in targets:
        distance = max(0.0, _distance(zone.center, target.position)
                       - max(0.0, target.radius))
        if distance > zone.radius or target.fire_multiplier <= 0.0:
            continue
        ratio = distance / zone.radius
        damage = spec.fire_damage * (1.0 - 0.45 * ratio)
        events.append(DamageEvent(
            target_id=target.target_id,
            source_projectile_id=zone.source_projectile_id,
            owner_id=zone.owner_id,
            cause="fire",
            damage=damage * target.fire_multiplier,
            impulse=(0.0, 0.0),
            status="burning",
            status_steps=spec.burn_status_steps,
        ))
    return tuple(events)


class ThrowableSystem:
    """Own inventory, cooldowns, projectiles, and persistent fire hazards."""

    def __init__(self, inventory: Optional[Mapping[str, int]] = None):
        supplied = inventory or {}
        unknown = set(supplied) - set(THROWABLE_ORDER)
        if unknown:
            raise ValueError(f"unknown throwable kinds: {sorted(unknown)!r}")
        self._inventory = {
            kind: min(THROWABLE_SPECS[kind].inventory_limit,
                      max(0, int(supplied.get(kind, 0))))
            for kind in THROWABLE_ORDER
        }
        self._cooldowns = {kind: 0 for kind in THROWABLE_ORDER}
        self._projectiles: list[_Projectile] = []
        self._fire_zones: list[_FireZone] = []
        self._next_projectile_id = 1
        self._next_zone_id = 1

    def inventory(self, kind: str) -> int:
        self._require_kind(kind)
        return self._inventory[kind]

    def cooldown_remaining(self, kind: str) -> int:
        self._require_kind(kind)
        return self._cooldowns[kind]

    def add_inventory(self, kind: str, amount: int) -> int:
        """Add pickups and return the accepted amount, capped by capacity."""
        self._require_kind(kind)
        if amount < 0:
            raise ValueError("amount must be non-negative")
        before = self._inventory[kind]
        self._inventory[kind] = min(
            THROWABLE_SPECS[kind].inventory_limit, before + int(amount))
        return self._inventory[kind] - before

    def can_throw(self, kind: str) -> tuple[bool, str]:
        self._require_kind(kind)
        if self._inventory[kind] <= 0:
            return False, "empty"
        if self._cooldowns[kind] > 0:
            return False, "cooldown"
        return True, "ok"

    def throw(self, kind: str, origin: Vec2, direction: Vec2,
              owner_id: Optional[Hashable] = None,
              power: float = 1.0) -> ThrowResult:
        """Attempt a throw; failed attempts consume neither ammo nor cooldown."""
        allowed, reason = self.can_throw(kind)
        if not allowed:
            return ThrowResult(False, reason)
        length = math.hypot(direction[0], direction[1])
        if length <= 1e-9:
            raise ValueError("throw direction must be non-zero")
        spec = THROWABLE_SPECS[kind]
        power = min(1.0, max(0.35, float(power)))
        dx, dy = direction[0] / length, direction[1] / length
        projectile = _Projectile(
            projectile_id=self._next_projectile_id,
            kind=kind,
            owner_id=owner_id,
            x=float(origin[0]),
            y=float(origin[1]),
            vx=dx * spec.throw_speed * power,
            vy=dy * spec.throw_speed * power,
            height=8.0,
            vz=spec.lift_speed * (0.65 + 0.35 * power),
            fuse_remaining=spec.fuse_steps,
        )
        self._next_projectile_id += 1
        self._inventory[kind] -= 1
        self._cooldowns[kind] = spec.cooldown_steps
        self._projectiles.append(projectile)
        return ThrowResult(True, "ok", self._projectile_view(projectile))

    def projectiles(self) -> tuple[ProjectileView, ...]:
        return tuple(self._projectile_view(item) for item in self._projectiles)

    def fire_zones(self) -> tuple[FireZoneView, ...]:
        return tuple(self._fire_zone_view(item) for item in self._fire_zones)

    def update(self, steps: int = 1,
               targets: Iterable[TargetSnapshot] = (),
               collision_query: Optional[CollisionQuery] = None) -> UpdateEvents:
        """Advance exact fixed steps and return all ordered events produced."""
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 0:
            raise ValueError("steps must be a non-negative integer")
        target_tuple = tuple(targets)
        self._validate_targets(target_tuple)
        impacts: list[ImpactEvent] = []
        blasts: list[BlastEvent] = []
        fires_started: list[FireStartedEvent] = []
        damage: list[DamageEvent] = []
        fires_expired: list[int] = []

        for _ in range(steps):
            for kind in THROWABLE_ORDER:
                self._cooldowns[kind] = max(0, self._cooldowns[kind] - 1)
            for projectile in tuple(self._projectiles):
                self._advance_projectile(
                    projectile, target_tuple, collision_query,
                    impacts, blasts, fires_started, damage)
            self._advance_fire_zones(target_tuple, damage, fires_expired)

        return UpdateEvents(tuple(impacts), tuple(blasts), tuple(fires_started),
                            tuple(damage), tuple(fires_expired))

    def _advance_projectile(self, projectile: _Projectile,
                            targets: tuple[TargetSnapshot, ...],
                            collision_query: Optional[CollisionQuery],
                            impacts: list[ImpactEvent],
                            blasts: list[BlastEvent],
                            fires_started: list[FireStartedEvent],
                            damage: list[DamageEvent]) -> None:
        spec = THROWABLE_SPECS[projectile.kind]
        projectile.fuse_remaining -= 1
        old_position = (projectile.x, projectile.y)

        if not projectile.grounded:
            new_position = (projectile.x + projectile.vx,
                            projectile.y + projectile.vy)
            hit_wall = bool(collision_query and
                            collision_query(old_position, new_position))
            if hit_wall:
                impacts.append(ImpactEvent(projectile.projectile_id,
                                           projectile.kind, old_position, "wall"))
                if projectile.kind == FIRE_BOTTLE:
                    self._ignite(projectile, old_position, fires_started)
                    return
                projectile.height = 0.0
                projectile.vz = 0.0
                projectile.vx = projectile.vy = 0.0
                projectile.grounded = True
            else:
                projectile.x, projectile.y = new_position
                projectile.height += projectile.vz
                projectile.vz -= spec.gravity
                if projectile.height <= 0.0 and projectile.vz <= 0.0:
                    projectile.height = 0.0
                    impacts.append(ImpactEvent(
                        projectile.projectile_id, projectile.kind,
                        (projectile.x, projectile.y), "ground"))
                    if projectile.kind == FIRE_BOTTLE:
                        self._ignite(projectile, (projectile.x, projectile.y),
                                     fires_started)
                        return
                    if projectile.bounce_count < 2 and (
                            abs(projectile.vx) + abs(projectile.vy) > 0.55):
                        projectile.bounce_count += 1
                        projectile.vz = abs(projectile.vz) * spec.bounce
                        projectile.vx *= spec.ground_friction
                        projectile.vy *= spec.ground_friction
                    else:
                        projectile.vx = projectile.vy = projectile.vz = 0.0
                        projectile.grounded = True

        if projectile.fuse_remaining <= 0:
            if projectile.kind == TIMED_EXPLOSIVE:
                blast = BlastEvent(
                    projectile_id=projectile.projectile_id,
                    owner_id=projectile.owner_id,
                    center=(projectile.x, projectile.y),
                    radius=spec.blast_radius,
                    max_damage=spec.max_damage,
                    edge_damage=spec.edge_damage,
                )
                blasts.append(blast)
                damage.extend(damage_from_blast(blast, targets))
                self._projectiles.remove(projectile)
            else:
                self._ignite(projectile, (projectile.x, projectile.y),
                             fires_started)

    def _ignite(self, projectile: _Projectile, center: Vec2,
                fires_started: list[FireStartedEvent]) -> None:
        spec = THROWABLE_SPECS[FIRE_BOTTLE]
        zone = _FireZone(
            zone_id=self._next_zone_id,
            source_projectile_id=projectile.projectile_id,
            owner_id=projectile.owner_id,
            x=center[0],
            y=center[1],
            remaining_steps=spec.fire_steps,
            next_damage_in=0,
        )
        self._next_zone_id += 1
        self._fire_zones.append(zone)
        self._projectiles.remove(projectile)
        fires_started.append(FireStartedEvent(
            zone.zone_id, projectile.projectile_id, projectile.owner_id,
            center, spec.fire_radius, spec.fire_steps))

    def _advance_fire_zones(self, targets: tuple[TargetSnapshot, ...],
                            damage: list[DamageEvent],
                            fires_expired: list[int]) -> None:
        for zone in tuple(self._fire_zones):
            if zone.next_damage_in <= 0:
                damage.extend(damage_from_fire(self._fire_zone_view(zone), targets))
                zone.next_damage_in = THROWABLE_SPECS[FIRE_BOTTLE].fire_tick_steps
            zone.next_damage_in -= 1
            zone.remaining_steps -= 1
            if zone.remaining_steps <= 0:
                self._fire_zones.remove(zone)
                fires_expired.append(zone.zone_id)

    @staticmethod
    def _projectile_view(projectile: _Projectile) -> ProjectileView:
        return ProjectileView(
            projectile.projectile_id, projectile.kind, projectile.owner_id,
            (projectile.x, projectile.y), (projectile.vx, projectile.vy),
            projectile.height, projectile.vz, projectile.fuse_remaining,
            projectile.bounce_count, projectile.grounded)

    @staticmethod
    def _fire_zone_view(zone: _FireZone) -> FireZoneView:
        return FireZoneView(
            zone.zone_id, zone.source_projectile_id, zone.owner_id,
            (zone.x, zone.y), THROWABLE_SPECS[FIRE_BOTTLE].fire_radius,
            zone.remaining_steps, zone.next_damage_in)

    @staticmethod
    def _require_kind(kind: str) -> None:
        if kind not in THROWABLE_SPECS:
            raise ValueError(f"unknown throwable kind: {kind!r}")

    @staticmethod
    def _validate_targets(targets: tuple[TargetSnapshot, ...]) -> None:
        seen = set()
        for target in targets:
            if target.target_id in seen:
                raise ValueError(f"duplicate target id: {target.target_id!r}")
            seen.add(target.target_id)
            if target.radius < 0.0:
                raise ValueError("target radius must be non-negative")
