"""Focused tests for deterministic, renderer-free throwable gameplay."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import throwables as T  # noqa: E402


def _throw(system, kind, origin=(0.0, 0.0), direction=(1.0, 0.0), owner="player"):
    result = system.throw(kind, origin, direction, owner_id=owner)
    assert result.success, result.reason
    return result.projectile


def test_inventory_limits_cooldown_and_failed_attempts_are_explicit():
    system = T.ThrowableSystem({T.TIMED_EXPLOSIVE: 99})
    spec = T.THROWABLE_SPECS[T.TIMED_EXPLOSIVE]
    assert system.inventory(T.TIMED_EXPLOSIVE) == spec.inventory_limit

    first = _throw(system, T.TIMED_EXPLOSIVE)
    assert first.projectile_id == 1
    assert system.inventory(T.TIMED_EXPLOSIVE) == spec.inventory_limit - 1
    blocked = system.throw(T.TIMED_EXPLOSIVE, (0, 0), (1, 0))
    assert (blocked.success, blocked.reason, blocked.projectile) == (
        False, "cooldown", None)

    system.update(spec.cooldown_steps)
    assert system.cooldown_remaining(T.TIMED_EXPLOSIVE) == 0
    _throw(system, T.TIMED_EXPLOSIVE)
    accepted = system.add_inventory(T.TIMED_EXPLOSIVE, 99)
    assert accepted == 2
    assert system.inventory(T.TIMED_EXPLOSIVE) == spec.inventory_limit


def test_timed_explosive_has_an_arc_bounces_and_detonates_on_exact_fuse():
    system = T.ThrowableSystem({T.TIMED_EXPLOSIVE: 1})
    initial = _throw(system, T.TIMED_EXPLOSIVE, direction=(3, 4))
    system.update(12)
    airborne = system.projectiles()[0]
    assert airborne.height > initial.height
    assert airborne.position[0] > 0 and airborne.position[1] > 0

    fuse = T.THROWABLE_SPECS[T.TIMED_EXPLOSIVE].fuse_steps
    before = system.update(fuse - 13)
    assert before.blasts == ()
    assert system.projectiles()[0].bounce_count >= 1
    detonation = system.update(1)
    assert len(detonation.blasts) == 1
    assert detonation.blasts[0].projectile_id == initial.projectile_id
    assert system.projectiles() == ()


def test_wall_collision_ignites_bottle_but_only_stops_timed_explosive():
    wall = lambda _old, new: new[0] >= 20.0

    bottle_system = T.ThrowableSystem({T.FIRE_BOTTLE: 1})
    bottle = _throw(bottle_system, T.FIRE_BOTTLE)
    events = bottle_system.update(10, collision_query=wall)
    assert len(events.impacts) == 1
    assert events.impacts[0].surface == "wall"
    assert events.fires_started[0].projectile_id == bottle.projectile_id
    assert bottle_system.projectiles() == ()
    assert len(bottle_system.fire_zones()) == 1

    explosive_system = T.ThrowableSystem({T.TIMED_EXPLOSIVE: 1})
    explosive = _throw(explosive_system, T.TIMED_EXPLOSIVE)
    events = explosive_system.update(10, collision_query=wall)
    assert events.blasts == ()
    stopped = explosive_system.projectiles()[0]
    assert stopped.projectile_id == explosive.projectile_id
    assert stopped.grounded and stopped.velocity == (0.0, 0.0)


def test_blast_damage_falls_off_and_respects_target_size_and_multiplier():
    blast = T.BlastEvent(7, "player", (0.0, 0.0), 100.0, 120.0, 20.0)
    targets = (
        T.TargetSnapshot("center", (0, 0)),
        T.TargetSnapshot("middle", (50, 0)),
        T.TargetSnapshot("edge", (100, 0)),
        T.TargetSnapshot("large", (110, 0), radius=20),
        T.TargetSnapshot("armoured", (50, 0), blast_multiplier=0.5),
        T.TargetSnapshot("outside", (121, 0), radius=20),
    )
    events = {event.target_id: event for event in T.damage_from_blast(blast, targets)}
    assert events["center"].damage > events["middle"].damage > events["edge"].damage
    assert events["large"].damage > 0
    assert math.isclose(events["armoured"].damage,
                        events["middle"].damage * 0.5)
    assert "outside" not in events
    assert events["middle"].impulse[0] > 0
    assert events["middle"].status == "staggered"


def test_fire_is_persistent_ticks_damage_and_applies_burning_status():
    system = T.ThrowableSystem({T.FIRE_BOTTLE: 1})
    _throw(system, T.FIRE_BOTTLE)
    # A full-power bottle lands about 256 px downrange; stand the target in
    # the resulting pool instead of back at the thrower's feet.
    target = T.TargetSnapshot("cop", (256, 0), radius=8)

    ignition = system.update(90, targets=(target,))
    assert len(ignition.fires_started) == 1
    fire_hits = [event for event in ignition.damage if event.cause == "fire"]
    assert fire_hits
    assert all(event.status == "burning" for event in fire_hits)
    assert all(event.status_steps == T.SIM_HZ * 2 for event in fire_hits)

    zone = system.fire_zones()[0]
    remaining = zone.remaining_steps
    later = system.update(remaining, targets=(target,))
    assert any(event.cause == "fire" for event in later.damage)
    assert later.fires_expired == (zone.zone_id,)
    assert system.fire_zones() == ()


def test_fire_query_has_soft_edge_and_fire_immunity():
    zone = T.FireZoneView(1, 4, "player", (10, 10), 60, 120, 0)
    targets = (
        T.TargetSnapshot("near", (10, 10)),
        T.TargetSnapshot("far", (65, 10)),
        T.TargetSnapshot("immune", (10, 10), fire_multiplier=0),
        T.TargetSnapshot("outside", (71, 10)),
    )
    events = {event.target_id: event for event in T.damage_from_fire(zone, targets)}
    assert events["near"].damage > events["far"].damage > 0
    assert set(events) == {"near", "far"}


def test_batched_and_single_step_updates_produce_identical_state_and_events():
    def make_system():
        item = T.ThrowableSystem({T.TIMED_EXPLOSIVE: 1, T.FIRE_BOTTLE: 1})
        _throw(item, T.TIMED_EXPLOSIVE, origin=(8, 2), direction=(1, 0.25))
        _throw(item, T.FIRE_BOTTLE, origin=(-5, 1), direction=(0.7, 1))
        return item

    target = T.TargetSnapshot("victim", (60, 18), radius=8)
    batched = make_system()
    batch_events = batched.update(180, targets=(target,))

    stepped = make_system()
    impacts = []
    blasts = []
    fires = []
    damage = []
    expired = []
    for _ in range(180):
        events = stepped.update(1, targets=(target,))
        impacts.extend(events.impacts)
        blasts.extend(events.blasts)
        fires.extend(events.fires_started)
        damage.extend(events.damage)
        expired.extend(events.fires_expired)

    assert tuple(impacts) == batch_events.impacts
    assert tuple(blasts) == batch_events.blasts
    assert tuple(fires) == batch_events.fires_started
    assert tuple(damage) == batch_events.damage
    assert tuple(expired) == batch_events.fires_expired
    assert stepped.projectiles() == batched.projectiles()
    assert stepped.fire_zones() == batched.fire_zones()


def test_invalid_inputs_fail_before_mutating_state():
    system = T.ThrowableSystem({T.FIRE_BOTTLE: 1})
    with pytest.raises(ValueError, match="non-zero"):
        system.throw(T.FIRE_BOTTLE, (0, 0), (0, 0))
    assert system.inventory(T.FIRE_BOTTLE) == 1
    assert system.projectiles() == ()
    with pytest.raises(ValueError, match="non-negative integer"):
        system.update(1.5)
    with pytest.raises(ValueError, match="duplicate target"):
        system.update(targets=(T.TargetSnapshot("same", (0, 0)),
                               T.TargetSnapshot("same", (1, 0))))
