"""
backend.main
FastAPI application entry point.
Exposes REST endpoints for NDI source discovery, device listing, and RX/TX control.
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from typing import List
import json
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.models import (
    NDISourceItem,
    VideoDeviceItem,
    AudioDeviceItem,
    RxStartRequest,
    RxSwitchRequest,
    RxStatus,
    TxStartRequest,
    TxStatus,
)
from backend.ndi_scanner import scanner
from backend.devices import list_video_devices, list_audio_devices
from backend.rx_runner import rx_runner
from backend.tx_runner import tx_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background NDI finder scanner on startup
    scanner.start()
    yield
    # Cleanup on shutdown
    scanner.stop()
    rx_runner.stop()
    tx_runner.stop()


app = FastAPI(
    title="utone-ndi-utils API",
    description="REST API to control NDI RX (Viewer) and TX (Sender)",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local Nuxt dev server (typically port 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Server-Sent Events (SSE) Stream ---
@app.get("/api/events", tags=["SSE"])
async def events_stream(request: Request):
    """
    Server-Sent Events endpoint pushing NDI sources and RX/TX statuses.
    Sends full state periodically (or immediately on change) without frontend polling.
    """
    async def event_generator():
        last_payload_str = ""
        while True:
            if await request.is_disconnected():
                break

            sources = [s.model_dump() for s in scanner.get_sources()]
            rx_stat = rx_runner.get_status().model_dump()
            tx_stat = tx_runner.get_status().model_dump()

            current_payload = {
                "sources": sources,
                "rx": rx_stat,
                "tx": tx_stat,
            }
            payload_str = json.dumps(current_payload, sort_keys=True)

            # Send update immediately if changed, or heartbeat ping periodically
            if payload_str != last_payload_str:
                last_payload_str = payload_str
                yield f"event: state\ndata: {payload_str}\n\n"
            else:
                yield ": keepalive\n\n"

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# --- NDI Discovery Endpoints ---
@app.get("/api/ndi/sources", response_model=List[NDISourceItem], tags=["NDI"])
def get_ndi_sources():
    """Get list of currently detected NDI sources on the local network."""
    return scanner.get_sources()


# --- Device Discovery Endpoints ---
@app.get("/api/devices/video", response_model=List[VideoDeviceItem], tags=["Devices"])
def get_video_devices():
    """List available video capture devices."""
    return list_video_devices()


@app.get("/api/devices/audio", response_model=List[AudioDeviceItem], tags=["Devices"])
def get_audio_devices():
    """List available audio capture devices."""
    return list_audio_devices()


# --- RX (Receiver / Viewer) Endpoints ---
@app.get("/api/rx/status", response_model=RxStatus, tags=["RX"])
def get_rx_status():
    """Get current status of NDI RX viewer."""
    return rx_runner.get_status()


@app.post("/api/rx/start", response_model=RxStatus, tags=["RX"])
def start_rx(req: RxStartRequest):
    """Start NDI RX viewer window with specified source."""
    try:
        rx_runner.start(
            sender_name=req.sender_name,
            recv_fmt=req.recv_fmt,
            recv_bandwidth=req.recv_bandwidth,
            fullscreen=req.fullscreen,
        )
        return rx_runner.get_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rx/switch", response_model=RxStatus, tags=["RX"])
def switch_rx(req: RxSwitchRequest):
    """Switch active NDI source without closing the viewer window."""
    try:
        rx_runner.switch_source(req.sender_name)
        return rx_runner.get_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rx/stop", response_model=RxStatus, tags=["RX"])
def stop_rx():
    """Stop NDI RX viewer window."""
    rx_runner.stop()
    return rx_runner.get_status()


# --- TX (Sender) Endpoints ---
@app.get("/api/tx/status", response_model=TxStatus, tags=["TX"])
def get_tx_status():
    """Get current status of NDI TX sender."""
    return tx_runner.get_status()


@app.post("/api/tx/start", response_model=TxStatus, tags=["TX"])
def start_tx(req: TxStartRequest):
    """Start NDI TX sender."""
    try:
        tx_runner.start(req)
        return tx_runner.get_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/tx/stop", response_model=TxStatus, tags=["TX"])
def stop_tx():
    """Stop NDI TX sender."""
    tx_runner.stop()
    return tx_runner.get_status()


# --- Serve Nuxt static build if exists ---
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", ".output", "public")
if os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
