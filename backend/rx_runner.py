"""
backend.rx_runner
Process / Thread controller for NDI Receiver.
Runs SDL2 window in a controlled process/thread with dynamic source switching.
"""
from __future__ import annotations
import multiprocessing as mp
import time
import queue
from typing import Optional
from backend.models import RxStatus


def _rx_worker_process(command_q: mp.Queue, status_q: mp.Queue, init_options: dict):
    # Import inside subprocess to avoid OpenGL / SDL context sharing issues
    import sdl2
    import sdl2.ext
    from OpenGL.GL import (
        GL_TEXTURE_2D, GL_PROJECTION, GL_MODELVIEW, GL_COLOR_BUFFER_BIT,
        GL_RGBA, GL_BGRA, GL_UNSIGNED_BYTE, GL_QUADS, GL_LINEAR,
        glEnable, glViewport, glMatrixMode, glLoadIdentity, glOrtho,
        glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
        glTexSubImage2D, glClearColor, glClear, glBegin, glTexCoord2f,
        glVertex2f, glEnd, glDeleteTextures
    )
    from cyndilib.receiver import Receiver
    from cyndilib.video_frame import VideoFrameSync
    from cyndilib.finder import Finder
    from core.rx import RecvFmt, Bandwidth, Options, render_texture, render_waiting_message, init_window

    finder = Finder()
    options = Options(
        sender_name=init_options["sender_name"],
        recv_fmt=RecvFmt.from_str(init_options.get("recv_fmt", "rgb")),
        recv_bandwidth=Bandwidth.from_str(init_options.get("recv_bandwidth", "highest")),
        fullscreen=init_options.get("fullscreen", False),
    )

    try:
        window = init_window("NDI Viewer", 1280, 720, options.fullscreen)
    except Exception as e:
        status_q.put({"type": "error", "error": f"Failed to init SDL window: {e}"})
        return

    w_ptr, h_ptr = sdl2.c_int(), sdl2.c_int()
    sdl2.SDL_GetWindowSize(window, w_ptr, h_ptr)
    win_w, win_h = w_ptr.value, h_ptr.value

    glEnable(GL_TEXTURE_2D)
    glViewport(0, 0, win_w, win_h)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glOrtho(-1, 1, -1, 1, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()

    texture_id = glGenTextures(1)
    receiver: Optional[Receiver] = None
    vf = VideoFrameSync()

    current_source_name = options.sender_name
    running = True
    event = sdl2.SDL_Event()
    is_connected = False
    reconnect_cooldown_until = 0.0

    last_frame_data = None
    last_frame_w, last_frame_h = 0, 0
    is_texture_initialized = False
    last_status_report = 0.0
    frames_rendered = 0

    try:
        while running:
            # 1. Process commands from main API process
            while not command_q.empty():
                try:
                    cmd = command_q.get_nowait()
                    action = cmd.get("action")
                    if action == "stop":
                        running = False
                        break
                    elif action == "switch":
                        new_source = cmd.get("sender_name")
                        if new_source and new_source != current_source_name:
                            current_source_name = new_source
                            if receiver is not None:
                                receiver = None
                            is_connected = False
                            reconnect_cooldown_until = 0.0
                            is_texture_initialized = False
                            last_frame_data = None
                    elif action == "toggle_fullscreen":
                        flags = sdl2.SDL_GetWindowFlags(window)
                        is_fs = bool(flags & sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP)
                        sdl2.SDL_SetWindowFullscreen(
                            window,
                            0 if is_fs else sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP
                        )
                except queue.Empty:
                    break

            if not running:
                break

            # 2. SDL Event processing
            while sdl2.SDL_PollEvent(event):
                if event.type == sdl2.SDL_QUIT:
                    running = False
                elif event.type == sdl2.SDL_KEYDOWN and event.key.keysym.sym == sdl2.SDLK_ESCAPE:
                    running = False
                elif event.type == sdl2.SDL_WINDOWEVENT and event.window.event == sdl2.SDL_WINDOWEVENT_RESIZED:
                    win_w, win_h = event.window.data1, event.window.data2
                    glViewport(0, 0, win_w, win_h)

            # 3. Connection and frame rendering
            if not is_connected:
                render_waiting_message()
                if time.time() >= reconnect_cooldown_until:
                    try:
                        finder.wait_for_sources(0)
                        matched = None
                        for s in finder:
                            if s.name == current_source_name or s.stream_name == current_source_name:
                                matched = s
                                break
                        if matched is not None:
                            receiver = Receiver(
                                color_format=options.recv_fmt.value,
                                bandwidth=options.recv_bandwidth.value,
                            )
                            receiver.frame_sync.set_video_frame(vf)
                            receiver.set_source(matched)
                            is_connected = True
                        else:
                            reconnect_cooldown_until = time.time() + 1.0
                    except Exception as e:
                        receiver = None
                        reconnect_cooldown_until = time.time() + 2.0
                        is_connected = False
            else:
                if not receiver or not receiver.is_connected():
                    is_connected = False
                    receiver = None
                    reconnect_cooldown_until = time.time() + 2.0
                    last_frame_data, last_frame_w, last_frame_h = None, 0, 0
                    is_texture_initialized = False
                else:
                    try:
                        receiver.frame_sync.capture_video()
                        tex_w, tex_h = vf.get_resolution()
                        if tex_w > 0 and tex_h > 0 and vf.get_data_size() > 0:
                            last_frame_data = bytes(vf)
                            if last_frame_w != tex_w or last_frame_h != tex_h:
                                is_texture_initialized = False
                            last_frame_w, last_frame_h = tex_w, tex_h
                            frames_rendered += 1

                        is_texture_initialized = render_texture(
                            last_frame_data, last_frame_w, last_frame_h, win_w, win_h,
                            texture_id, options.recv_fmt, is_texture_initialized
                        )
                    except Exception:
                        is_connected = False
                        receiver = None
                        reconnect_cooldown_until = time.time() + 2.0
                        is_texture_initialized = False

            sdl2.SDL_GL_SwapWindow(window)

            # Report status every 0.5 sec
            now = time.time()
            elapsed = now - last_status_report
            if elapsed >= 0.5:
                real_fps = round(frames_rendered / elapsed, 1) if elapsed > 0 else 0.0
                frames_rendered = 0
                last_status_report = now
                status_q.put({
                    "type": "status",
                    "running": True,
                    "is_connected": is_connected,
                    "current_source": current_source_name,
                    "width": last_frame_w,
                    "height": last_frame_h,
                    "fps_real": real_fps,
                })

    except Exception as e:
        status_q.put({"type": "error", "error": str(e)})
    finally:
        receiver = None
        glDeleteTextures(1, [texture_id])
        sdl2.SDL_DestroyWindow(window)
        sdl2.SDL_Quit()
        status_q.put({"type": "status", "running": False, "is_connected": False, "current_source": None, "width": 0, "height": 0})


class RxRunner:
    def __init__(self):
        self.process: Optional[mp.Process] = None
        self.command_q: Optional[mp.Queue] = None
        self.status_q: Optional[mp.Queue] = None
        self._current_status = RxStatus(
            running=False,
            is_connected=False,
            current_source=None,
            width=0,
            height=0
        )

    def get_status(self) -> RxStatus:
        self._update_status_from_queue()
        if self.process and not self.process.is_alive():
            self._current_status.running = False
            self._current_status.is_connected = False
            self.process = None
        return self._current_status

    def _update_status_from_queue(self):
        if not self.status_q:
            return
        while not self.status_q.empty():
            try:
                msg = self.status_q.get_nowait()
                if msg.get("type") == "status":
                    self._current_status.running = msg.get("running", False)
                    self._current_status.is_connected = msg.get("is_connected", False)
                    self._current_status.current_source = msg.get("current_source")
                    self._current_status.width = msg.get("width", 0)
                    self._current_status.height = msg.get("height", 0)
                    self._current_status.fps_real = msg.get("fps_real", 0.0)
                elif msg.get("type") == "error":
                    self._current_status.error = msg.get("error")
            except queue.Empty:
                break

    def start(self, sender_name: str, recv_fmt: str = "rgb", recv_bandwidth: str = "highest", fullscreen: bool = False):
        if self.process and self.process.is_alive():
            raise RuntimeError("RX is already running. Please switch source or stop first.")

        self.command_q = mp.Queue()
        self.status_q = mp.Queue()
        self._current_status = RxStatus(
            running=True,
            is_connected=False,
            current_source=sender_name,
            recv_fmt=recv_fmt,
            recv_bandwidth=recv_bandwidth,
            fullscreen=fullscreen,
            width=0,
            height=0,
            error=None
        )

        init_opts = {
            "sender_name": sender_name,
            "recv_fmt": recv_fmt,
            "recv_bandwidth": recv_bandwidth,
            "fullscreen": fullscreen
        }

        self.process = mp.Process(
            target=_rx_worker_process,
            args=(self.command_q, self.status_q, init_opts),
            daemon=True
        )
        self.process.start()

    def switch_source(self, sender_name: str):
        if not self.process or not self.process.is_alive():
            # If not running, start it
            self.start(sender_name=sender_name)
            return

        if self.command_q:
            self.command_q.put({"action": "switch", "sender_name": sender_name})
            self._current_status.current_source = sender_name

    def stop(self):
        if self.command_q:
            try:
                self.command_q.put_nowait({"action": "stop"})
            except Exception:
                pass

        if self.process and self.process.is_alive():
            self.process.join(timeout=1.0)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=0.5)

        self.process = None
        self.command_q = None
        self.status_q = None
        self._current_status = RxStatus(
            running=False,
            is_connected=False,
            current_source=None,
            width=0,
            height=0,
            error=None
        )


rx_runner = RxRunner()
