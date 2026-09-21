"""
backend.preview_manager
On-demand NDI video preview streamer using MJPEG (multipart/x-mixed-replace).
Captures frames using cyndilib with low bandwidth and encodes them to JPEG with cv2.
Supports different frame rate targets:
- thumbnail: ~2-3 fps, width ~360px (very low CPU/network usage for multi-view grid)
- full: ~20 fps, width ~720px (smooth for enlarged modal)
"""
from __future__ import annotations
import asyncio
import time
import threading
from typing import Dict, Optional, Set, Tuple
import numpy as np
import cv2

from cyndilib.finder import Finder
from cyndilib.receiver import Receiver
from cyndilib.video_frame import VideoFrameSync
from cyndilib.wrapper.ndi_recv import RecvColorFormat, RecvBandwidth


class NDIPreviewSession:
    """Manages a lightweight NDI Receiver connection for a single source."""
    def __init__(self, source_name: str, finder: Finder):
        self.source_name = source_name
        self.finder = finder
        # Subscribers map: queue -> (target_fps, max_width)
        self.subscribers: Dict[asyncio.Queue, Tuple[int, int]] = {}
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.thread = None

    def add_subscriber(self, q: asyncio.Queue, fps: int = 3, max_width: int = 360):
        with self.lock:
            self.subscribers[q] = (fps, max_width)

    def remove_subscriber(self, q: asyncio.Queue):
        with self.lock:
            self.subscribers.pop(q, None)

    def _worker(self):
        receiver: Optional[Receiver] = None
        vf = VideoFrameSync()
        reconnect_time = 0.0

        # Cache encoded frames for identical resolutions to avoid duplicate encoding
        last_sub_send_time: Dict[asyncio.Queue, float] = {}

        while self.running:
            with self.lock:
                subs = dict(self.subscribers)

            if not subs:
                time.sleep(0.2)
                continue

            now = time.time()
            if receiver is None or not receiver.is_connected():
                if now >= reconnect_time:
                    try:
                        self.finder.wait_for_sources(0)
                        matched = None
                        for s in self.finder:
                            if s.name == self.source_name or s.stream_name == self.source_name:
                                matched = s
                                break

                        if matched is not None:
                            receiver = Receiver(
                                color_format=RecvColorFormat.BGRX_BGRA,
                                bandwidth=RecvBandwidth.lowest,
                            )
                            receiver.frame_sync.set_video_frame(vf)
                            receiver.set_source(matched)
                        else:
                            reconnect_time = now + 1.0
                    except Exception:
                        receiver = None
                        reconnect_time = now + 2.0
                time.sleep(0.1)
                continue

            # Determine who actually needs a frame right now based on their target FPS
            active_targets = []
            for q, (fps, max_w) in subs.items():
                min_interval = 1.0 / max(1, fps)
                last_t = last_sub_send_time.get(q, 0.0)
                if now - last_t >= min_interval:
                    active_targets.append((q, max_w))

            if not active_targets:
                time.sleep(0.02)
                continue

            # Capture frame
            try:
                receiver.frame_sync.capture_video()
                w, h = vf.get_resolution()
                if w > 0 and h > 0 and vf.get_data_size() > 0:
                    raw_data = bytes(vf)
                    arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((h, w, 4))

                    # Group subscribers by max_width to encode only once per resolution
                    width_groups: Dict[int, list] = {}
                    for q, max_w in active_targets:
                        width_groups.setdefault(max_w, []).append(q)

                    for max_w, queues in width_groups.items():
                        if w > max_w:
                            new_w = max_w
                            new_h = int(h * (max_w / w))
                            resized = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                        else:
                            resized = arr

                        bgr = cv2.cvtColor(resized, cv2.COLOR_BGRA2BGR)
                        quality = 65 if max_w <= 360 else 75
                        success, enc = cv2.imencode('.jpg', bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                        if success:
                            jpeg_bytes = enc.tobytes()
                            for q in queues:
                                last_sub_send_time[q] = now
                                try:
                                    if q.full():
                                        try:
                                            q.get_nowait()
                                        except Exception:
                                            pass
                                    q.put_nowait(jpeg_bytes)
                                except Exception:
                                    pass

            except Exception:
                receiver = None
                reconnect_time = now + 2.0

            # Clean up old queue timestamps
            for q in list(last_sub_send_time.keys()):
                if q not in subs:
                    last_sub_send_time.pop(q, None)

            # Sleep briefly to not spin
            time.sleep(0.02)

        if receiver is not None:
            receiver = None


class NDIPreviewManager:
    """Manages multiple NDI preview sessions by source name."""
    def __init__(self):
        self.finder = Finder()
        self.sessions: Dict[str, NDIPreviewSession] = {}
        self.lock = threading.Lock()

    def get_or_create_session(self, source_name: str) -> NDIPreviewSession:
        with self.lock:
            if source_name not in self.sessions:
                session = NDIPreviewSession(source_name, self.finder)
                session.start()
                self.sessions[source_name] = session
            return self.sessions[source_name]

    def cleanup_idle_sessions(self):
        """Stops and removes sessions with 0 subscribers."""
        with self.lock:
            to_remove = []
            for name, session in self.sessions.items():
                with session.lock:
                    if len(session.subscribers) == 0:
                        to_remove.append(name)
            for name in to_remove:
                self.sessions[name].stop()
                del self.sessions[name]

    def stop_all(self):
        with self.lock:
            for session in self.sessions.values():
                session.stop()
            self.sessions.clear()
        if hasattr(self.finder, "destroy"):
            try:
                self.finder.destroy()
            except Exception:
                pass


preview_manager = NDIPreviewManager()
