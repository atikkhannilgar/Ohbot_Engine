#!/usr/bin/env python3
"""
visualizer.py Playback recorded clips with synchronized video, audio, and transcription.

Plays the video with the audio, showing word-level transcription highlighted
in real-time as words are spoken.

Usage:
    python visualizer.py recordings/clip_0000
    python visualizer.py --clip-dir recordings/clip_0000

Controls:
    SPACE = pause/resume
    R     = restart from beginning
    Q/ESC = quit
    LEFT  = rewind 2s
    RIGHT = forward 2s

Requirements:
    pip install opencv-python sounddevice scipy numpy
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import sounddevice as sd
from scipy.io import wavfile


class ClipPlayer:
    def __init__(self, clip_dir):
        self.clip_dir = Path(clip_dir)
        self.video_path = self.clip_dir / "video.avi"
        self.audio_path = self.clip_dir / "audio.wav"
        self.meta_path = self.clip_dir / "meta.json"

        if not self.meta_path.exists():
            print(f"ERROR: {self.meta_path} not found")
            sys.exit(1)

        with open(self.meta_path) as f:
            self.meta = json.load(f)

        self.sentence = self.meta["sentence"]
        self.word_timings = self.meta.get("word_timings") or []
        self.audio_sr = self.meta.get("audio_sr", 16000)
        self.video_fps = self.meta.get("video_fps", 30.0)
        self.duration = self.meta.get("duration_s", 0)

        self.audio_data = None
        if self.audio_path.exists():
            sr, data = wavfile.read(str(self.audio_path))
            self.audio_data = data.astype(np.float32) / 32768.0
            self.audio_sr = sr

        self.cap = None
        if self.video_path.exists():
            self.cap = cv2.VideoCapture(str(self.video_path))

        self.playing = False
        self.current_time = 0.0
        self.start_wall_time = 0.0
        self.audio_stream = None

    def get_current_words(self, t):
        """Return (past_words, current_word, future_words) based on time t."""
        past = []
        current = None
        future = []

        for wt in self.word_timings:
            if wt["end"] <= t:
                past.append(wt["word"])
            elif wt["start"] <= t <= wt["end"]:
                current = wt["word"]
            else:
                future.append(wt["word"])

        return past, current, future

    def draw_transcription(self, frame, t):
        """Draw the sentence with the current word highlighted."""
        h, w = frame.shape[:2]

        past, current, future = self.get_current_words(t)

        past_text = " ".join(past)
        current_text = current or ""
        future_text = " ".join(future)

        y = h - 60
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.55
        thickness = 1

        cv2.rectangle(frame, (0, y - 30), (w, h), (0, 0, 0), -1)

        x = 10
        if past_text:
            size = cv2.getTextSize(past_text + " ", font, scale, thickness)[0]
            cv2.putText(frame, past_text + " ", (x, y),
                        font, scale, (150, 150, 150), thickness)
            x += size[0]

        if current_text:
            size = cv2.getTextSize(current_text, font, scale, thickness)[0]
            cv2.rectangle(frame, (x - 2, y - size[1] - 4),
                          (x + size[0] + 2, y + 6), (0, 100, 255), -1)
            cv2.putText(frame, current_text, (x, y),
                        font, scale, (255, 255, 255), thickness + 1)
            x += size[0]
            if future_text:
                cv2.putText(frame, " ", (x, y), font, scale, (150, 150, 150), thickness)
                x += cv2.getTextSize(" ", font, scale, thickness)[0][0]

        if future_text:
            cv2.putText(frame, future_text, (x, y),
                        font, scale, (200, 200, 200), thickness)

        full_sentence_y = y + 25
        cv2.putText(frame, f"[{t:.1f}s / {self.duration:.1f}s]  \"{self.sentence[:80]}\"",
                    (10, full_sentence_y), font, 0.4, (100, 200, 100), 1)

    def draw_waveform(self, frame, t):
        """Draw a small waveform with playhead position."""
        if self.audio_data is None:
            return

        h, w = frame.shape[:2]
        wf_h = 50
        wf_y = 5
        wf_x = 10
        wf_w = w - 20

        cv2.rectangle(frame, (wf_x, wf_y), (wf_x + wf_w, wf_y + wf_h), (30, 30, 30), -1)

        n_samples = len(self.audio_data)
        samples_per_pixel = max(1, n_samples // wf_w)
        mid_y = wf_y + wf_h // 2

        for px in range(0, wf_w, 2):
            start_s = px * samples_per_pixel
            end_s = min(start_s + samples_per_pixel, n_samples)
            if start_s >= n_samples:
                break
            chunk = self.audio_data[start_s:end_s]
            amp = min(float(np.max(np.abs(chunk))), 1.0)
            bar_h = int(amp * (wf_h // 2 - 2))
            color = (100, 180, 100)
            cv2.line(frame, (wf_x + px, mid_y - bar_h),
                     (wf_x + px, mid_y + bar_h), color, 1)

        progress = t / self.duration if self.duration > 0 else 0
        head_x = wf_x + int(progress * wf_w)
        cv2.line(frame, (head_x, wf_y), (head_x, wf_y + wf_h), (0, 0, 255), 2)

    def play_audio_from(self, start_time):
        """Start audio playback from a given time offset."""
        if self.audio_stream is not None:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None

        if self.audio_data is None:
            return

        start_sample = int(start_time * self.audio_sr)
        if start_sample >= len(self.audio_data):
            return

        remaining = self.audio_data[start_sample:]
        self._audio_pos = 0
        self._audio_remaining = remaining

        def callback(outdata, frames, time_info, status):
            end = self._audio_pos + frames
            chunk = self._audio_remaining[self._audio_pos:end]
            if len(chunk) < frames:
                outdata[:len(chunk), 0] = chunk
                outdata[len(chunk):, 0] = 0
                raise sd.CallbackStop
            else:
                outdata[:, 0] = chunk
            self._audio_pos = end

        self.audio_stream = sd.OutputStream(
            samplerate=self.audio_sr,
            channels=1,
            dtype="float32",
            callback=callback,
            blocksize=1024,
        )
        self.audio_stream.start()

    def stop_audio(self):
        if self.audio_stream is not None:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None

    def play(self):
        if self.cap is None:
            print("ERROR: No video file found")
            return

        total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_duration = 1.0 / self.video_fps

        self.current_time = 0.0
        self.playing = True
        self.play_audio_from(0.0)

        print(f"\nPlaying: {self.clip_dir.name}")
        print(f"  Sentence: \"{self.sentence}\"")
        print(f"  Duration: {self.duration:.1f}s, {total_frames} frames @ {self.video_fps:.0f}fps")
        print(f"  Words aligned: {len(self.word_timings)}")
        print(f"  [SPACE=pause, R=restart, LEFT/RIGHT=seek, Q=quit]\n")

        self.start_wall_time = time.time()
        pause_offset = 0.0

        while True:
            if self.playing:
                self.current_time = time.time() - self.start_wall_time - pause_offset

                frame_idx = int(self.current_time * self.video_fps)
                if frame_idx >= total_frames:
                    self.playing = False
                    self.stop_audio()
                    print("  [Playback finished. R=restart, Q=quit]")
                    frame_idx = total_frames - 1

                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
                if not ret:
                    break

            self.draw_waveform(frame, self.current_time)
            self.draw_transcription(frame, self.current_time)

            if not self.playing:
                cv2.putText(frame, "PAUSED", (frame.shape[1] // 2 - 50, frame.shape[0] // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

            cv2.imshow("Clip Viewer", frame)
            key = cv2.waitKey(int(frame_duration * 1000)) & 0xFF

            if key == ord("q") or key == 27:
                break
            elif key == ord(" "):
                if self.playing:
                    self.playing = False
                    self.stop_audio()
                    pause_start = time.time()
                else:
                    self.playing = True
                    pause_offset += time.time() - pause_start
                    self.play_audio_from(self.current_time)
            elif key == ord("r"):
                self.current_time = 0.0
                self.start_wall_time = time.time()
                pause_offset = 0.0
                self.playing = True
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.play_audio_from(0.0)
            elif key == 81 or key == 2:  # LEFT arrow
                seek_to = max(0, self.current_time - 2.0)
                self.start_wall_time = time.time() - seek_to
                pause_offset = 0.0
                self.current_time = seek_to
                if self.playing:
                    self.play_audio_from(seek_to)
            elif key == 83 or key == 3:  # RIGHT arrow
                seek_to = min(self.duration, self.current_time + 2.0)
                self.start_wall_time = time.time() - seek_to
                pause_offset = 0.0
                self.current_time = seek_to
                if self.playing:
                    self.play_audio_from(seek_to)

        self.stop_audio()
        self.cap.release()
        cv2.destroyAllWindows()


def main():
    p = argparse.ArgumentParser(description="Visualize a recorded training clip")
    p.add_argument("clip_dir", nargs="?", help="Path to clip directory (e.g. recordings/clip_0000)")
    p.add_argument("--clip-dir", dest="clip_dir_flag", default=None,
                   help="Alternative: path to clip directory")
    args = p.parse_args()

    clip_dir = args.clip_dir or args.clip_dir_flag
    if not clip_dir:
        print("ERROR: provide a clip directory path")
        print("  python visualizer.py recordings/clip_0000")
        sys.exit(1)

    player = ClipPlayer(clip_dir)
    player.play()


if __name__ == "__main__":
    main()
