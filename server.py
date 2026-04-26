"""FastAPI server — wraps the Agent class in HTTP endpoints."""
from __future__ import annotations
import uuid, logging, queue, json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from agent import Agent, State

# ── Log broadcasting ───────────────────────────────────────────────────
# Every log entry is pushed into this queue and streamed to the browser
_log_queue: queue.Queue = queue.Queue(maxsize=500)

class UILogHandler(logging.Handler):
    """Sends log records to the browser via SSE."""
    LEVEL_STYLE = {
        "USER":  "user",
        "AGENT": "agent",
        "LLM":   "llm",
        "API":   "api",
        "STATE": "state",
        "INFO":  "info",
        "ERROR": "error",
    }
    def emit(self, record):
        msg = self.format(record)
        # Classify by content
        kind = "info"
        if "USER  →" in msg:   kind = "user"
        elif "AGENT →" in msg: kind = "agent"
        elif "[LLM]" in msg:   kind = "llm"
        elif "[API]" in msg:   kind = "api"
        elif "STATE" in msg:   kind = "state"
        elif "ERROR" in msg or "error" in msg.lower(): kind = "error"
        elif "SESSION" in msg: kind = "session"
        try:
            _log_queue.put_nowait({
                "time": datetime.now().strftime("%H:%M:%S"),
                "kind": kind,
                "msg":  msg.strip(),
            })
        except queue.Full:
            pass

# ── Logging setup ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("payassist")
ui_handler = UILogHandler()
ui_handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(ui_handler)

app = FastAPI(title="PayAssist API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, Agent] = {}


class MessageRequest(BaseModel):
    session_id: str
    message: str

class MessageResponse(BaseModel):
    session_id: str
    message: str
    state: str


@app.post("/session", response_model=dict)
def create_session():
    session_id = str(uuid.uuid4())
    agent = Agent()
    response = agent.next("")
    _sessions[session_id] = agent
    log.info(f"━━ NEW SESSION [{session_id[:8]}] ━━")
    log.info(f"STATE → {agent._state.name}")
    return {"session_id": session_id, "message": response["message"], "state": agent._state.name}


@app.post("/chat", response_model=MessageResponse)
def chat(req: MessageRequest):
    agent = _sessions.get(req.session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found.")

    sid = req.session_id[:8]
    state_before = agent._state.name

    log.info(f"USER  → \"{req.message}\"")
    log.info(f"STATE → {state_before}")

    response = agent.next(req.message)
    state_after = agent._state.name

    log.info(f"AGENT → \"{response['message'][:120]}\"")
    if state_before != state_after:
        log.info(f"STATE {state_before} → {state_after}")
    log.info("─" * 40)

    return MessageResponse(session_id=req.session_id, message=response["message"], state=state_after)


@app.get("/logs")
async def stream_logs():
    """SSE endpoint — streams log events to the browser in real time."""
    def event_stream():
        # Send a heartbeat first so browser knows connection is alive
        yield "data: {}\"\n\n"
        while True:
            try:
                entry = _log_queue.get(timeout=30)
                yield f"data: {json.dumps(entry)}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    _sessions.pop(session_id, None)
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "sessions": len(_sessions)}


app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")