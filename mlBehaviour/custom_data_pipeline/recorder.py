#!/usr/bin/env python3
"""
recorder.py Raw training data capture tool.

Displays sentences one at a time. Press SPACE to start recording (webcam + mic),
press SPACE again to stop. Saves raw video + audio + sentence text.

Alignment and feature extraction are done separately (see align.py / extract.py)
so the raw data can be reprocessed without re-recording.

Saves per clip:
    recordings/<clip_id>/video.avi    webcam video (MJPG)
    recordings/<clip_id>/audio.wav    16kHz mono audio
    recordings/<clip_id>/meta.json    sentence text, duration, fps

Usage:
    python recorder.py [--sentences sentences.txt] [--out-dir ./recordings]
                       [--camera 1] [--sample-rate 16000]

Requirements:
    pip install opencv-python sounddevice scipy
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import sounddevice as sd
from scipy.io import wavfile


def load_sentences(path):
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


class Recorder:
    def __init__(self, camera_id=1, sample_rate=16000, out_dir="./recordings"):
        self.camera_id = camera_id
        self.sample_rate = sample_rate
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.cap = None
        self.recording = False
        self.audio_chunks = []
        self.frames = []
        self.fps = 30.0

    def open_camera(self):
        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            print(f"ERROR: Cannot open camera {self.camera_id}")
            sys.exit(1)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        print(f"[camera] opened device {self.camera_id}, fps={self.fps:.1f}")

    def close_camera(self):
        if self.cap:
            self.cap.release()

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}")
        if self.recording:
            self.audio_chunks.append(indata.copy())

    def start_recording(self):
        self.audio_chunks = []
        self.frames = []
        self.recording = True

    def stop_recording(self):
        self.recording = False

    def get_audio_array(self):
        if not self.audio_chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self.audio_chunks, axis=0).flatten()

    def save_clip(self, clip_id, sentence):
        clip_dir = self.out_dir / clip_id
        clip_dir.mkdir(parents=True, exist_ok=True)

        video_path = clip_dir / "video.avi"
        audio_path = clip_dir / "audio.wav"
        meta_path = clip_dir / "meta.json"

        if self.frames:
            h, w = self.frames[0].shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(str(video_path), fourcc, self.fps, (w, h))
            for frame in self.frames:
                writer.write(frame)
            writer.release()

        audio = self.get_audio_array()
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        wavfile.write(str(audio_path), self.sample_rate, audio_int16)

        duration = len(audio) / self.sample_rate if self.sample_rate > 0 else 0

        meta = {
            "sentence": sentence,
            "duration_s": round(duration, 4),
            "audio_sr": self.sample_rate,
            "video_fps": self.fps,
            "n_video_frames": len(self.frames),
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        print(f"  Saved to {clip_dir} ({duration:.1f}s, {len(self.frames)} frames)")

    def run_session(self, sentences):
        self.open_camera()

        existing = [d.name for d in self.out_dir.iterdir() if d.is_dir()]
        start_idx = len(existing)

        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self.audio_callback,
            blocksize=1024,
        )

        print("\n" + "=" * 60)
        print("  RECORDING SESSION")
        print("  SPACE = start/stop recording")
        print("  S     = skip sentence")
        print("  Q     = quit")
        print("=" * 60 + "\n")

        clip_idx = start_idx
        sentence_idx = 0

        with stream:
            while sentence_idx < len(sentences):
                sentence = sentences[sentence_idx]
                clip_id = f"clip_{clip_idx:04d}"

                print(f"\n--- Sentence {sentence_idx + 1}/{len(sentences)} ---")
                print(f"  \"{sentence}\"")
                print(f"  [SPACE to start recording, S to skip, Q to quit]")

                state = "waiting"

                while True:
                    ret, frame = self.cap.read()
                    if not ret:
                        print("[camera] frame grab failed, retrying...")
                        time.sleep(0.1)
                        continue

                    display = frame.copy()

                    if state == "waiting":
                        cv2.putText(display, "READY - Press SPACE to record",
                                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                    elif state == "recording":
                        cv2.putText(display, "RECORDING - Press SPACE to stop",
                                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                        elapsed = time.time() - self._rec_start
                        cv2.putText(display, f"{elapsed:.1f}s",
                                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                        self.frames.append(frame)

                    wrapped = self._wrap_text(sentence, max_width=60)
                    y_offset = display.shape[0] - 20 * len(wrapped) - 10
                    for i, line in enumerate(wrapped):
                        cv2.putText(display, line, (10, y_offset + i * 25),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                    cv2.imshow("Recorder", display)
                    key = cv2.waitKey(1) & 0xFF

                    if key == ord(" "):
                        if state == "waiting":
                            state = "recording"
                            self._rec_start = time.time()
                            self.start_recording()
                            print("  [Recording started...]")
                        elif state == "recording":
                            self.stop_recording()
                            print("  [Recording stopped]")
                            break

                    elif key == ord("s"):
                        if state == "recording":
                            self.stop_recording()
                        print("  [Skipped]")
                        sentence_idx += 1
                        break

                    elif key == ord("q") or key == 27:
                        if state == "recording":
                            self.stop_recording()
                        print("\n[quit] Session ended.")
                        self.close_camera()
                        cv2.destroyAllWindows()
                        return

                if state != "recording" and len(self.frames) == 0:
                    continue

                if len(self.frames) > 0:
                    self.save_clip(clip_id, sentence)
                    clip_idx += 1
                    sentence_idx += 1

        self.close_camera()
        cv2.destroyAllWindows()
        print(f"\n[done] {clip_idx - start_idx} clips recorded to {self.out_dir}")

    def _wrap_text(self, text, max_width=60):
        words = text.split()
        lines = []
        current = ""
        for w in words:
            if len(current) + len(w) + 1 > max_width:
                lines.append(current)
                current = w
            else:
                current = f"{current} {w}" if current else w
        if current:
            lines.append(current)
        return lines


def main():
    p = argparse.ArgumentParser(description="Record webcam+audio training data with sentence prompts")
    p.add_argument("--sentences", default=str(Path(__file__).parent / "sentences.txt"),
                   help="Text file with one sentence per line")
    p.add_argument("--out-dir", default=str(Path(__file__).parent / "recordings"),
                   help="Output directory for recorded clips")
    p.add_argument("--camera", type=int, default=1, help="Camera device index")
    p.add_argument("--sample-rate", type=int, default=16000, help="Audio sample rate")
    args = p.parse_args()

    sentences = load_sentences(args.sentences)
    if not sentences:
        print(f"ERROR: No sentences found in {args.sentences}")
        sys.exit(1)
    print(f"Loaded {len(sentences)} sentences from {args.sentences}")

    rec = Recorder(camera_id=args.camera, sample_rate=args.sample_rate, out_dir=args.out_dir)
    rec.run_session(sentences)


if __name__ == "__main__":
    main()
