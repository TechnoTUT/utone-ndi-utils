from __future__ import annotations

from typing import NamedTuple, TYPE_CHECKING
from typing_extensions import Self
import enum
import time

import click

from cyndilib.wrapper.ndi_structs import FourCC
from cyndilib.wrapper.ndi_recv import RecvColorFormat, RecvBandwidth
from cyndilib.video_frame import VideoFrameSync
from cyndilib.receiver import Receiver
from cyndilib.finder import Finder
if TYPE_CHECKING:
    from cyndilib.finder import Source

import sdl2
import sdl2.ext
from OpenGL.GL import *
from OpenGL.GLU import *


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
    sender_name: str = 'ffmpeg_sender'
    recv_fmt: RecvFmt = RecvFmt.rgb
    recv_bandwidth: Bandwidth = Bandwidth.highest
    fullscreen: bool = False


def get_source(finder: Finder, name: str) -> Source:
    click.echo('Waiting for NDI sources...')
    finder.wait_for_sources(10)
    for source in finder:
        if source.name == name or source.stream_name == name:
            return source
    raise Exception(f'Source not found. Available sources: {finder.get_source_names()}')


def wait_for_first_frame(receiver: Receiver) -> None:
    vf = receiver.frame_sync.video_frame
    assert vf is not None
    click.echo('Waiting for the first frame...')
    while receiver.is_connected():
        receiver.frame_sync.capture_video()
        resolution = vf.get_resolution()
        if min(resolution) > 0 and vf.get_data_size() > 0:
            click.echo('Frame received.')
            return
        time.sleep(0.01)


def render_texture(frame: bytes, tex_w: int, tex_h: int, win_w: int, win_h: int, texture_id: int, recv_fmt: RecvFmt, is_texture_initialized: bool):
    if not frame or tex_w == 0 or tex_h == 0:
        render_waiting_message()
        return False # 初期化されていないことを返す

    gl_format = GL_BGRA if recv_fmt == RecvFmt.bgr else GL_RGBA

    glBindTexture(GL_TEXTURE_2D, texture_id)
    
    # 初回または解像度変更時のみメモリを確保、それ以外は一部更新で高速化
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
    
    return True # 初期化済みであることを返す


def render_waiting_message():
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)


def init_window(title: str, width: int, height: int, fullscreen: bool):
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
    sdl2.SDL_GL_SetSwapInterval(0)
    sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)
    return window


def play_sdl(options: Options):
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
    
    finder = None
    receiver = None
    
    running = True
    event = sdl2.SDL_Event()
    
    is_connected = False
    reconnect_cooldown_until = 0
    
    last_frame_data = None
    last_frame_w, last_frame_h = 0, 0
    is_texture_initialized = False

    try:
        finder = Finder()
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
                    click.echo("Attempting to connect to NDI source...")
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
                            if i > 30: raise Exception('Timeout')
                            time.sleep(0.1)
                            i += 1
                        
                        wait_for_first_frame(receiver)
                        is_connected = True
                        click.echo("Connected to NDI source.")

                    except Exception as e:
                        click.echo(f"Error during connection attempt: {e}", err=True)
                        receiver = None
                        reconnect_cooldown_until = time.time() + 5.0
                        is_texture_initialized = False
            else:
                if not receiver or not receiver.is_connected():
                    click.echo("Connection lost.", err=True)
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
                            # 解像度が変わった場合はテクスチャの再初期化を促す
                            if last_frame_w != tex_w or last_frame_h != tex_h:
                                is_texture_initialized = False
                            last_frame_w, last_frame_h = tex_w, tex_h
                        
                        is_texture_initialized = render_texture(
                            last_frame_data, last_frame_w, last_frame_h, win_w, win_h, texture_id, options.recv_fmt, is_texture_initialized
                        )

                    except Exception as e:
                        click.echo(f"Error during frame capture or rendering: {e}", err=True)
                        is_connected = False
                        receiver = None
                        reconnect_cooldown_until = time.time() + 5.0
                        is_texture_initialized = False

            sdl2.SDL_GL_SwapWindow(window)
            # time.sleep(0.001)

    finally:
        click.echo("Cleaning up resources...")
        if finder and hasattr(finder, 'destroy'): finder.destroy()
        receiver = None
        
        glDeleteTextures(1, [texture_id])
        sdl2.SDL_DestroyWindow(window)
        sdl2.SDL_Quit()
        click.echo("Program terminated.")

# ... (main関数部分は変更なし) ...
@click.command()
@click.option('-s', '--sender-name', type=str, default='ffmpeg_sender', show_default=True, help='NDI source name to connect to')
@click.option('-f', '--recv-fmt', type=click.Choice(choices=[m.name for m in RecvFmt]), default='rgb', show_default=True, help='Pixel format for receiving')
@click.option('-b', '--recv-bandwidth', type=click.Choice(choices=[m.name for m in Bandwidth]), default='highest', show_default=True, help='Receiving bandwidth')
@click.option('--fullscreen', is_flag=True, help='Start in fullscreen mode')
def main(sender_name: str, recv_fmt: str, recv_bandwidth: str, fullscreen: bool):
    options = Options(
        sender_name=sender_name,
        recv_fmt=RecvFmt.from_str(recv_fmt),
        recv_bandwidth=Bandwidth.from_str(recv_bandwidth),
        fullscreen=fullscreen,
    )
    try:
        play_sdl(options)
    except Exception as e:
        click.echo(f"A fatal error occurred: {e}", err=True)

if __name__ == '__main__':
    main()