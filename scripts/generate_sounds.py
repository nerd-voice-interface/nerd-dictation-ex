#!/usr/bin/env python3
"""
Генерация звуков для nerd-dictation-ex с использованием MIDI и FluidSynth.

Требования:
    - fluidsynth
    - soundfont-fluid (или другой .sf2)
    - midiutil (pip install midiutil)

Использование:
    python generate_sounds.py

Звуки рендерятся в .wav файлы через fluidsynth без воспроизведения.
"""

from midiutil import MIDIFile
import subprocess
import os
import sys

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "..", "sounds")
SOUNDFONT = "/usr/share/soundfonts/FluidR3_GM.sf2"

# MIDI инструменты (General MIDI):
# 0 = Acoustic Grand Piano
# 8 = Celesta
# 9 = Glockenspiel
# 10 = Music Box
# 11 = Vibraphone
# 12 = Marimba
# 13 = Xylophone
# 14 = Tubular Bells

# MIDI ноты:
# C4=60, D4=62, E4=64, F4=65, G4=67, A4=69, B4=71
# C5=72, D5=74, E5=76, F5=77, G5=79, A5=81, B5=83, C6=84


def create_midi(filename, notes, instrument=0, tempo=240):
    """
    Создать MIDI файл.

    Args:
        filename: путь к файлу
        notes: список кортежей (pitch, start_time, duration, velocity)
        instrument: номер инструмента GM (0-127)
        tempo: темп в BPM
    """
    midi = MIDIFile(1)
    midi.addTempo(0, 0, tempo)
    midi.addProgramChange(0, 0, 0, instrument)

    for pitch, start, duration, velocity in notes:
        midi.addNote(0, 0, pitch, start, duration, velocity)

    with open(filename, 'wb') as f:
        midi.writeFile(f)
    return filename


def render_midi_to_wav(midi_path, wav_path):
    """Рендерить MIDI в WAV файл через fluidsynth."""
    subprocess.run([
        'fluidsynth', '-F', wav_path, '-ni',
        SOUNDFONT, midi_path
    ], capture_output=True, check=True)


def main():
    os.makedirs(SOUNDS_DIR, exist_ok=True)

    # begin.wav - Music Box (10), восходящий G4 -> C5
    print("Generating begin sound (Music Box, G4 -> C5)...")
    notes_begin = [
        (67, 0, 0.3, 80),     # G4
        (72, 0.15, 0.4, 90),  # C5
    ]
    midi_path = os.path.join(SOUNDS_DIR, "begin.mid")
    wav_path = os.path.join(SOUNDS_DIR, "begin.wav")
    create_midi(midi_path, notes_begin, instrument=10, tempo=300)
    render_midi_to_wav(midi_path, wav_path)
    print(f"  Saved: {wav_path}")

    # end.wav - Music Box (10), нисходящий E5 -> C5
    print("Generating end sound (Music Box, E5 -> C5)...")
    notes_end = [
        (76, 0, 0.3, 80),     # E5
        (72, 0.15, 0.4, 70),  # C5
    ]
    midi_path = os.path.join(SOUNDS_DIR, "end.mid")
    wav_path = os.path.join(SOUNDS_DIR, "end.wav")
    create_midi(midi_path, notes_end, instrument=10, tempo=300)
    render_midi_to_wav(midi_path, wav_path)
    print(f"  Saved: {wav_path}")

    # execute.wav - Celesta (8), нисходящий A5 -> E5
    print("Generating execute sound (Celesta, A5 -> E5)...")
    notes_execute = [
        (81, 0, 0.25, 85),    # A5
        (76, 0.12, 0.35, 75), # E5
    ]
    midi_path = os.path.join(SOUNDS_DIR, "execute.mid")
    wav_path = os.path.join(SOUNDS_DIR, "execute.wav")
    create_midi(midi_path, notes_execute, instrument=8, tempo=320)
    render_midi_to_wav(midi_path, wav_path)
    print(f"  Saved: {wav_path}")

    print("\nDone! WAV files saved to:", SOUNDS_DIR)


if __name__ == "__main__":
    main()
