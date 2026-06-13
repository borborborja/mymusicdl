"""Server-Sent Events — a single multiplexed stream of job/tool progress.

The browser opens one EventSource on ``/api/events``; the worker and updater publish to the broker
and every connected client receives the snapshots. Heartbeat comments keep the connection alive
through Cloudflare.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.app.deps import get_broker

router = APIRouter()


@router.get("/events")
async def events(request: Request, broker=Depends(get_broker)):
    queue = broker.subscribe()

    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
