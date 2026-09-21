"""
core.rx
NDI Receiver, SDL2/OpenGL display logic, and playback loop.
"""
from __future__ import annotations

import enum
import time
import sys
from typing import NamedTuple, Optional, TYPE_CHECKING
from typing_extensions import Self

from cyndilib.wrapper.ndi_recv import RecvColorFormat, RecvBandwidth
from cyndilib.video_frame import VideoFrameSync
from cyndilib.receiver import Receiver
from cyndilib.finder import Finder
if TYPE_CHECKING:
    from cyndilib.finder import Source

import sdl2
import sdl2.ext
from OpenGL.GL import (
    GL_TEXTURE_2D, GL_PROJECTION, GL_MODELVIEW, GL_COLOR_BUFFER_BIT,
    GL_RGBA, GL_BGRA, GL_UNSIGNED_BYTE, GL_QUADS, GL_LINEAR,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    glEnable, glViewport, glMatrixMode, glLoadIdentity, glOrtho,
    glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
    glTexSubImage2D, glClearColor, glClear, glBegin, glTexCoord2f,
    glVertex2f, glEnd, glDeleteTextures
)


class RecvFmt(enum.Enum):
    uyvy = RecvColorFormat.UYVY_RGBA
    rgb = RecvColorFormat.RGBX_RGBA
    bgr = RecvColorFormat.BGRX_BGRA

    @classmethod
    def from_str(cls, name: str) -> Self:
        return cls.__members__[name]


class Bandwidth(enum.Enum):
    lowest = RecvBandwidth.lowest
    highest = RecvBandwidth.highest

    @classmethod
    def from_str(cls, name: str) -> Self:
        return cls.__members__[name]


class Options(NamedTuple):
    sender_name: str
    recv_fmt: RecvFmt = RecvFmt.rgb
    recv_bandwidth: Bandwidth = Bandwidth.highest
    fullscreen: bool = False


def get_source(finder: Finder, name: str, timeout_seconds: float = 10.0) -> Source:
    """Wait for and find a specific NDI source by full name or stream name."""
    max_loops = int(timeout_seconds * 10)
    for _ in range(max_loops):
        finder.wait_for_sources(0)
        for source in finder:
            if source.name == name or source.stream_name == name:
                return source
        time.sleep(0.1)
    raise Exception(f'Source "{name}" not found. Available sources: {finder.get_source_names()}')


def wait_for_first_frame(receiver: Receiver) -> None:
    """Block until first valid video frame is received."""
    vf = receiver.frame_sync.video_frame
    assert vf is not None
    while receiver.is_connected():
        receiver.frame_sync.capture_video()
        resolution = vf.get_resolution()
        if min(resolution) > 0 and vf.get_data_size() > 0:
            return
        time.sleep(0.01)


def render_texture(
    frame: bytes,
    tex_w: int,
    tex_h: int,
    win_w: int,
    win_h: int,
    texture_id: int,
    recv_fmt: RecvFmt,
    is_texture_initialized: bool
) -> bool:
    """Render raw frame bytes to SDL OpenGL window with aspect ratio scaling."""
    if not frame or tex_w == 0 or tex_h == 0:
        render_waiting_message()
        return False

    gl_format = GL_BGRA if recv_fmt == RecvFmt.bgr else GL_RGBA
    glBindTexture(GL_TEXTURE_2D, texture_id)
    
    if not is_texture_initialized:
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tex_w, tex_h, 0, gl_format, GL_UNSIGNED_BYTE, frame)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    else:
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, tex_w, tex_h, gl_format, GL_UNSIGNED_BYTE, frame)

    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)

    src_ratio = tex_w / tex_h
    dst_ratio = win_w / win_h

    if src_ratio > dst_ratio:
        scale_x = 1.0
        scale_y = dst_ratio / src_ratio
    else:
        scale_x = src_ratio / dst_ratio
        scale_y = 1.0

    glBegin(GL_QUADS)
    glTexCoord2f(0.0, 1.0); glVertex2f(-scale_x, -scale_y)
    glTexCoord2f(1.0, 1.0); glVertex2f( scale_x, -scale_y)
    glTexCoord2f(1.0, 0.0); glVertex2f( scale_x,  scale_y)
    glTexCoord2f(0.0, 0.0); glVertex2f(-scale_x,  scale_y)
    glEnd()
    
    return True


def render_waiting_message() -> None:
    """Render empty/black screen when waiting for frames."""
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)


def init_window(title: str, width: int, height: int, fullscreen: bool):
    """Initialize SDL2 OpenGL window and context."""
    if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO) != 0:
        raise RuntimeError(f"SDL_Init Error: {sdl2.SDL_GetError()}")

    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 2)
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 1)
    
    flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_RESIZABLE
    if fullscreen:
        flags |= sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP

    window = sdl2.SDL_CreateWindow(
        title.encode('utf-8'),
        sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
        width, height,
        flags
    )
    if not window:
        raise RuntimeError(f"SDL_CreateWindow Error: {sdl2.SDL_GetError()}")

    sdl2.SDL_GL_CreateContext(window)
    sdl2.SDL_GL_SetSwapInterval(1)  # Enable vsync
    sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)
    return window


def play_sdl(options: Options, finder: Finder, log_fn=print):
    """Main SDL2 playback loop for CLI receiver."""
    window = init_window("NDI Viewer", 1280, 720, options.fullscreen)
    
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
    running = True
    event = sdl2.SDL_Event()
    
    is_connected = False
    reconnect_cooldown_until = 0.0
    last_frame_data = None
    last_frame_w, last_frame_h = 0, 0
    is_texture_initialized = False

    try:
        vf = VideoFrameSync()
        while running:
            while sdl2.SDL_PollEvent(event):
                if event.type == sdl2.SDL_QUIT:
                    running = False
                elif event.type == sdl2.SDL_KEYDOWN and event.key.keysym.sym == sdl2.SDLK_ESCAPE:
                    running = False
                elif event.type == sdl2.SDL_WINDOWEVENT and event.window.event == sdl2.SDL_WINDOWEVENT_RESIZED:
                    win_w, win_h = event.window.data1, event.window.data2
                    glViewport(0, 0, win_w, win_h)

            if not is_connected:
                render_waiting_message()
                if time.time() >= reconnect_cooldown_until:
                    log_fn("Attempting to connect to NDI source...")
                    try:
                        source = get_source(finder, options.sender_name)
                        receiver = Receiver(
                            color_format=options.recv_fmt.value,
                            bandwidth=options.recv_bandwidth.value,
                        )
                        receiver.frame_sync.set_video_frame(vf)
                        receiver.set_source(source)

                        i = 0
                        while not receiver.is_connected():
                            if i > 30:
                                raise Exception("Timeout")
                            time.sleep(0.1)
                            i += 1
                        
                        wait_for_first_frame(receiver)
                        is_connected = True
                        log_fn("Connected to NDI source.")
                    except Exception as e:
                        log_fn(f"Error during connection attempt: {e}")
                        receiver = None
                        reconnect_cooldown_until = time.time() + 5.0
                        is_texture_initialized = False
            else:
                if not receiver or not receiver.is_connected():
                    log_fn("Connection lost.")
                    is_connected = False
                    receiver = None
                    reconnect_cooldown_until = time.time() + 5.0
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
                        
                        is_texture_initialized = render_texture(
                            last_frame_data, last_frame_w, last_frame_h, win_w, win_h,
                            texture_id, options.recv_fmt, is_texture_initialized
                        )
                    except Exception as e:
                        log_fn(f"Error during frame capture or rendering: {e}")
                        is_connected = False
                        receiver = None
                        reconnect_cooldown_until = time.time() + 5.0
                        is_texture_initialized = False

            sdl2.SDL_GL_SwapWindow(window)

    finally:
        log_fn("Cleaning up resources...")
        receiver = None
        glDeleteTextures(1, [texture_id])
        sdl2.SDL_DestroyWindow(window)
        sdl2.SDL_Quit()
        log_fn("Program terminated.")
