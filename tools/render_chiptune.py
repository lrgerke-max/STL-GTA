#!/usr/bin/env python3
"""Render a deterministic chiptune WAV using note material from a MIDI file.

This intentionally uses only the Python standard library.  It supports Standard
MIDI format 0 and 1 files with ticks-per-quarter timing.
"""

from __future__ import annotations

import argparse
import bisect
import math
import os
import struct
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path


SAMPLE_RATE = 22_050
MIN_OUTPUT_SECONDS = 180.0


class MidiError(ValueError):
    pass


@dataclass(frozen=True)
class MidiNote:
    start_tick: int
    end_tick: int
    pitch: int
    velocity: int
    channel: int
    track: int


@dataclass(frozen=True)
class TimedNote:
    start: float
    duration: float
    pitch: int
    velocity: int
    channel: int
    track: int


def read_varlen(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if offset >= len(data):
            raise MidiError("truncated variable-length MIDI value")
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset
    raise MidiError("invalid variable-length MIDI value")


def parse_track(data: bytes, track_index: int) -> tuple[list[MidiNote], list[tuple[int, int]], int]:
    notes: list[MidiNote] = []
    tempos: list[tuple[int, int]] = []
    active: dict[tuple[int, int], list[tuple[int, int]]] = {}
    offset = 0
    tick = 0
    running_status: int | None = None

    while offset < len(data):
        delta, offset = read_varlen(data, offset)
        tick += delta
        if offset >= len(data):
            raise MidiError(f"track {track_index} ends after a delta time")

        first = data[offset]
        if first & 0x80:
            status = first
            offset += 1
            first_data: int | None = None
            if status < 0xF0:
                running_status = status
        else:
            if running_status is None:
                raise MidiError(f"track {track_index} uses running status before a status byte")
            status = running_status
            first_data = first
            offset += 1

        if status == 0xFF:
            if offset >= len(data):
                raise MidiError(f"truncated meta event in track {track_index}")
            meta_type = data[offset]
            offset += 1
            length, offset = read_varlen(data, offset)
            end = offset + length
            if end > len(data):
                raise MidiError(f"truncated meta payload in track {track_index}")
            payload = data[offset:end]
            offset = end
            if meta_type == 0x51 and length == 3:
                mpqn = int.from_bytes(payload, "big")
                if mpqn:
                    tempos.append((tick, mpqn))
            if meta_type == 0x2F:
                break
            continue

        if status in (0xF0, 0xF7):
            length, offset = read_varlen(data, offset)
            offset += length
            if offset > len(data):
                raise MidiError(f"truncated SysEx event in track {track_index}")
            running_status = None
            continue

        event_type = status & 0xF0
        channel = status & 0x0F
        data_length = 1 if event_type in (0xC0, 0xD0) else 2
        event_data: list[int] = []
        if first_data is not None:
            event_data.append(first_data)
        needed = data_length - len(event_data)
        if offset + needed > len(data):
            raise MidiError(f"truncated channel event in track {track_index}")
        event_data.extend(data[offset : offset + needed])
        offset += needed

        if event_type == 0x90 and event_data[1] > 0:
            key = (channel, event_data[0])
            active.setdefault(key, []).append((tick, event_data[1]))
        elif event_type == 0x80 or (event_type == 0x90 and event_data[1] == 0):
            key = (channel, event_data[0])
            starts = active.get(key)
            if starts:
                start_tick, velocity = starts.pop(0)
                if tick > start_tick:
                    notes.append(
                        MidiNote(start_tick, tick, key[1], velocity, channel, track_index)
                    )

    for (channel, pitch), starts in active.items():
        for start_tick, velocity in starts:
            if tick > start_tick:
                notes.append(MidiNote(start_tick, tick, pitch, velocity, channel, track_index))
    return notes, tempos, tick


def parse_midi(path: Path) -> tuple[list[TimedNote], float, int, int]:
    data = path.read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiError("not a Standard MIDI file")
    header_length = struct.unpack_from(">I", data, 4)[0]
    if header_length < 6 or 8 + header_length > len(data):
        raise MidiError("invalid MIDI header length")
    midi_format, track_count, division = struct.unpack_from(">HHH", data, 8)
    if midi_format not in (0, 1):
        raise MidiError(f"unsupported MIDI format {midi_format}; expected format 0 or 1")
    if division & 0x8000:
        raise MidiError("SMPTE MIDI timing is not supported")
    if division == 0:
        raise MidiError("MIDI ticks-per-quarter value is zero")

    offset = 8 + header_length
    all_notes: list[MidiNote] = []
    all_tempos: list[tuple[int, int]] = []
    max_tick = 0
    parsed_tracks = 0
    while offset + 8 <= len(data) and parsed_tracks < track_count:
        chunk_type = data[offset : offset + 4]
        chunk_length = struct.unpack_from(">I", data, offset + 4)[0]
        offset += 8
        chunk_end = offset + chunk_length
        if chunk_end > len(data):
            raise MidiError("truncated MIDI track chunk")
        if chunk_type == b"MTrk":
            notes, tempos, track_end = parse_track(data[offset:chunk_end], parsed_tracks)
            all_notes.extend(notes)
            all_tempos.extend(tempos)
            max_tick = max(max_tick, track_end)
            parsed_tracks += 1
        offset = chunk_end
    if parsed_tracks != track_count:
        raise MidiError(f"header declares {track_count} tracks, found {parsed_tracks}")
    if not all_notes:
        raise MidiError("MIDI contains no usable note events")

    # Later tempo events at the same tick replace earlier ones.
    tempo_at_tick = {0: 500_000}
    for tick, mpqn in all_tempos:
        tempo_at_tick[tick] = mpqn
    tempo_ticks = sorted(tempo_at_tick)
    tempo_values = [tempo_at_tick[tick] for tick in tempo_ticks]
    tempo_seconds = [0.0]
    for index in range(1, len(tempo_ticks)):
        elapsed_ticks = tempo_ticks[index] - tempo_ticks[index - 1]
        tempo_seconds.append(
            tempo_seconds[-1] + elapsed_ticks * tempo_values[index - 1] / (division * 1_000_000.0)
        )

    def tick_to_seconds(tick: int) -> float:
        index = bisect.bisect_right(tempo_ticks, tick) - 1
        return tempo_seconds[index] + (
            (tick - tempo_ticks[index]) * tempo_values[index] / (division * 1_000_000.0)
        )

    timed = [
        TimedNote(
            tick_to_seconds(note.start_tick),
            tick_to_seconds(note.end_tick) - tick_to_seconds(note.start_tick),
            note.pitch,
            note.velocity,
            note.channel,
            note.track,
        )
        for note in all_notes
        if note.end_tick > note.start_tick
    ]
    timed.sort(key=lambda note: (note.start, note.track, note.channel, note.pitch))
    source_duration = tick_to_seconds(max_tick)
    return timed, source_duration, midi_format, division


def midi_frequency(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def choose_voice(note: TimedNote, cycle: int, pitch: int) -> str:
    if note.channel == 9:
        return "noise"
    if pitch < 55:
        return "triangle"
    return ("pulse12", "pulse25", "square")[(note.channel + note.track + cycle) % 3]


def add_voice(
    mix: array,
    start_seconds: float,
    duration: float,
    pitch: int,
    velocity: int,
    voice: str,
    gain: float,
    seed: int,
) -> None:
    start = max(0, int(round(start_seconds * SAMPLE_RATE)))
    length = max(1, int(round(duration * SAMPLE_RATE)))
    end = min(len(mix), start + length)
    if start >= end:
        return

    attack = max(1, min(int(SAMPLE_RATE * 0.006), length // 4))
    release = max(1, min(int(SAMPLE_RATE * 0.035), length // 3))
    amplitude = gain * (0.28 + 0.72 * velocity / 127.0)
    frequency = midi_frequency(pitch)
    phase = ((seed * 0.61803398875) % 1.0)
    phase_step = frequency / SAMPLE_RATE
    lfsr = (seed & 0x7FFF) or 1
    noise_value = 0.0
    noise_hold = max(1, int(SAMPLE_RATE / max(900.0, min(7000.0, frequency * 18.0))))

    for sample_index in range(start, end):
        local = sample_index - start
        if local < attack:
            envelope = local / attack
        elif local >= length - release:
            envelope = max(0.0, (length - local - 1) / release)
        else:
            envelope = 1.0

        if voice == "noise":
            if local % noise_hold == 0:
                bit = ((lfsr >> 0) ^ (lfsr >> 1)) & 1
                lfsr = (lfsr >> 1) | (bit << 14)
                noise_value = 1.0 if lfsr & 1 else -1.0
            value = noise_value
        elif voice == "triangle":
            value = 1.0 - 4.0 * abs(phase - 0.5)
            phase = (phase + phase_step) % 1.0
        else:
            duty = 0.125 if voice == "pulse12" else 0.25 if voice == "pulse25" else 0.5
            # Offset the two pulse levels so narrow-duty voices do not add a large DC bias.
            value = (1.0 - duty) if phase < duty else -duty
            value /= max(duty, 1.0 - duty)
            phase = (phase + phase_step) % 1.0
        mix[sample_index] += value * amplitude * envelope


def render(notes: list[TimedNote], minimum_seconds: float) -> tuple[array, float, int]:
    first_note = min(note.start for note in notes)
    material = [
        TimedNote(
            note.start - first_note,
            max(0.035, note.duration),
            note.pitch,
            note.velocity,
            note.channel,
            note.track,
        )
        for note in notes
    ]
    last_note_end = max(note.start + note.duration for note in material)
    loop_seconds = max(1.0, last_note_end + 0.35)
    cycles = max(1, math.ceil(minimum_seconds / loop_seconds))
    output_seconds = cycles * loop_seconds
    sample_count = math.ceil(output_seconds * SAMPLE_RATE)
    mix = array("f", [0.0]) * sample_count

    unique_onsets = sorted({round(note.start, 6) for note in material})
    for cycle in range(cycles):
        mode = cycle % 4
        cycle_start = cycle * loop_seconds
        for index, note in enumerate(material):
            pitch = note.pitch
            if mode == 1 and pitch >= 64 and pitch <= 115:
                pitch += 12
            elif mode == 2 and pitch < 60 and pitch >= 12:
                pitch -= 12
            elif mode == 3 and pitch >= 72:
                pitch -= 12

            gate = (0.94, 0.62, 0.82, 0.72)[mode]
            duration = max(0.035, note.duration * gate)
            voice = choose_voice(note, cycle, pitch)
            gain = 0.19 if voice == "triangle" else 0.16 if voice == "noise" else 0.14
            seed = 1 + index + cycle * 131 + note.pitch * 17 + note.channel * 31

            if mode == 2 and note.duration >= 0.32 and voice != "noise":
                half = note.duration * 0.5
                add_voice(mix, cycle_start + note.start, half * 0.64, pitch, note.velocity,
                          voice, gain, seed)
                add_voice(mix, cycle_start + note.start + half, half * 0.64, pitch,
                          note.velocity, voice, gain * 0.86, seed + 7)
            else:
                add_voice(mix, cycle_start + note.start, duration, pitch, note.velocity,
                          voice, gain, seed)

            if mode == 3 and voice not in ("noise", "triangle") and note.duration >= 0.24:
                add_voice(
                    mix,
                    cycle_start + note.start + min(0.12, note.duration * 0.24),
                    max(0.035, duration * 0.55),
                    pitch,
                    note.velocity,
                    "pulse12",
                    gain * 0.22,
                    seed + 19,
                )

        # A quiet noise-clock uses only onset times already present in the source.
        for onset_index, onset in enumerate(unique_onsets):
            if (onset_index + cycle) % 4 == 0:
                source_pitch = material[onset_index % len(material)].pitch
                add_voice(
                    mix,
                    cycle_start + onset,
                    0.025 if onset_index % 2 else 0.045,
                    source_pitch,
                    48,
                    "noise",
                    0.045,
                    10_007 + onset_index + cycle * 97,
                )

    # One-pole DC blocker, followed by a short zero-to-zero boundary fade so the
    # finished WAV can be looped by Pygame without a hard discontinuity.
    previous_input = 0.0
    previous_output = 0.0
    peak = 0.0
    boundary_fade = max(1, int(SAMPLE_RATE * 0.045))
    for index, value in enumerate(mix):
        filtered = value - previous_input + 0.995 * previous_output
        previous_input = value
        previous_output = filtered
        if index < boundary_fade:
            filtered *= index / boundary_fade
        elif index >= len(mix) - boundary_fade:
            filtered *= max(0.0, (len(mix) - index - 1) / boundary_fade)
        mix[index] = filtered
        peak = max(peak, abs(filtered))

    if peak <= 0.0:
        raise MidiError("render produced no audible samples")
    scale = 0.88 / peak
    for index in range(len(mix)):
        mix[index] *= scale
    return mix, len(mix) / SAMPLE_RATE, cycles


def write_wave(path: Path, samples: array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        chunk_size = SAMPLE_RATE * 4
        for start in range(0, len(samples), chunk_size):
            pcm = array(
                "h",
                (
                    max(-32768, min(32767, int(sample * 32767.0)))
                    for sample in samples[start : start + chunk_size]
                ),
            )
            if sys.byteorder != "little":
                pcm.byteswap()
            wav_file.writeframesraw(pcm.tobytes())


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=project_root / "music" / "AUD_HO1036.mid",
        help="source Standard MIDI file",
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=project_root / "music" / "gloria-8bit.wav",
        help="destination mono PCM WAV",
    )
    parser.add_argument(
        "--minimum-seconds",
        type=float,
        default=MIN_OUTPUT_SECONDS,
        help="minimum arranged duration (default: 180)",
    )
    args = parser.parse_args()
    if args.minimum_seconds < MIN_OUTPUT_SECONDS:
        parser.error(f"--minimum-seconds must be at least {MIN_OUTPUT_SECONDS:g}")

    try:
        notes, source_duration, midi_format, division = parse_midi(args.source)
        samples, output_duration, cycles = render(notes, args.minimum_seconds)
        write_wave(args.output, samples)
    except (OSError, MidiError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    file_size = os.path.getsize(args.output)
    print(f"MIDI format: {midi_format}; ticks/quarter: {division}")
    print(f"Source duration: {source_duration:.2f} seconds")
    print(f"Output duration: {output_duration:.2f} seconds ({cycles} arranged cycles)")
    print(f"Note count: {len(notes)}")
    print(f"File size: {file_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
