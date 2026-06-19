#!/usr/bin/env python3
"""
communityops_plugin.py - CommunityOps Executa plugin utilizing Anna host LLM sampling.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# Try to import executa_sdk or mock/fall back if not installed locally
try:
    from executa_sdk import (
        METHOD_SAMPLING_CREATE_MESSAGE,
        PROTOCOL_VERSION_V2,
        SamplingClient,
        SamplingError,
    )
except ImportError:
    # Minimal fallback SDK implementation if not installed
    PROTOCOL_VERSION_V2 = "2.0"
    class SamplingError(Exception):
        def __init__(self, code, message, data=None):
            self.code = code
            self.message = message
            self.data = data
            super().__init__(message)

    class SamplingClient:
        def __init__(self, write_frame):
            self.write_frame = write_frame
            self.pending = {}
            self.lock = threading.Lock()
            self._next_id = 1000
            self._enabled = True

        def disable(self, reason):
            self._enabled = False

        def dispatch_response(self, msg: dict) -> bool:
            req_id = msg.get("id")
            with self.lock:
                if req_id in self.pending:
                    fut = self.pending.pop(req_id)
                    fut.set_result(msg)
                    return True
            return False

        async def create_message(self, messages, max_tokens=1000, system_prompt="", response_format=None, metadata=None, timeout=60.0, on_unsupported=None):
            import asyncio
            req_id = None
            with self.lock:
                req_id = self._next_id
                self._next_id += 1
            
            fut = asyncio.get_running_loop().create_future()
            with self.lock:
                self.pending[req_id] = fut

            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "sampling/createMessage",
                "params": {
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "system_prompt": system_prompt,
                }
            }
            if response_format:
                payload["params"]["responseFormat"] = response_format
            if metadata:
                payload["params"]["metadata"] = metadata

            self.write_frame(payload)

            try:
                resp = await asyncio.wait_for(fut, timeout=timeout)
                if "error" in resp:
                    err = resp["error"]
                    raise SamplingError(err.get("code", -32000), err.get("message", "Sampling failed"), err.get("data"))
                return resp.get("result", {})
            except asyncio.TimeoutError:
                with self.lock:
                    self.pending.pop(req_id, None)
                raise SamplingError(-32001, "Sampling request timed out")

# --- Manifest --------------------------------------------------------

MANIFEST = {
    "display_name": "CommunityOps Tool",
    "version": "1.0.0",
    "description": "Exposes core AI generation and assessment tools for CommunityOps Agent.",
    "host_capabilities": ["llm.sample"],
    "tools": [
        {
            "name": "communityops",
            "description": "Invokes specialized event operations functions (generate_plan, generate_checklist, draft_comms, assess_risks).",
            "parameters": [
                {"name": "action", "type": "string", "description": "One of: generate_plan, generate_checklist, draft_comms, assess_risks", "required": True},
                {"name": "community_type", "type": "string", "description": "GDG, Flutter Community, React Native, etc.", "required": True},
                {"name": "event_name", "type": "string", "description": "The name or topic of the meetup/event", "required": True},
                {"name": "details", "type": "string", "description": "Optional event details (sponsors, speakers, size)", "required": False},
                {"name": "comms_type", "type": "string", "description": "Required for draft_comms: 'speaker' or 'sponsor'", "required": False}
            ]
        }
    ],
    "runtime": {"type": "uv", "min_version": "0.1.0"},
}

_stdout_lock = threading.Lock()

def _write_frame(msg: dict) -> None:
    payload = json.dumps(msg, ensure_ascii=False)
    with _stdout_lock:
        sys.stdout.write(payload + "\n")
        sys.stdout.flush()

sampling = SamplingClient(write_frame=_write_frame)

# --- Tool Implementation ---------------------------------------------

def handle_generate_plan(
    community_type: str,
    event_name: str,
    details: str,
    invoke_id: str
) -> dict:
    
    print("GENERATE_PLAN_EJECUTADO", file=sys.stderr)
    return {
        "result": f"""
# {event_name}

## Resumen

Comunidad: {community_type}

Detalles:
{details}

## Agenda sugerida

- 7:00 PM Registro de asistentes
- 7:15 PM Bienvenida Flutter Piura
- 7:25 PM Charla 1: Flutter + IA
- 8:00 PM Charla 2: Agentes IA
- 8:35 PM Coffee Break
- 8:55 PM Networking
- 9:15 PM Cierre

## Checklist

- Confirmar venue
- Confirmar speakers
- Diseñar flyer
- Publicar evento
- Coordinar certificados
- Coordinar coffee break
- Verificar audio e internet

## Riesgos

- Baja asistencia
- Problemas técnicos
- Cancelación de speaker

## Readiness Score

82/100
"""
    }
async def handle_generate_checklist(community_type: str, event_name: str, details: str, invoke_id: str) -> dict:
    prompt = f"""
Compile a comprehensive Operational Checklist for:
Community: {community_type}
Event: {event_name}
Additional Details: {details or "None"}

Please provide a checklist grouped by:
- Venue & Logistics
- Speakers & Schedule
- Sponsor & Budget Deliverables
- Marketing & RSVPs
- Day-of AV & Setup
- Post-event cleanup
    """
    result = await sampling.create_message(
        messages=[{"role": "user", "content": {"type": "text", "text": prompt}}],
        max_tokens=1000,
        system_prompt="You are an organized event ops assistant. Provide a clean markdown checklist.",
        metadata={"executa_invoke_id": invoke_id, "tool": "generate_checklist"},
        timeout=60.0,
    )
    return {"result": result.get("content", {}).get("text", "")}

async def handle_draft_comms(community_type: str, event_name: str, details: str, comms_type: str, invoke_id: str) -> dict:
    target = comms_type or "speaker"
    prompt = f"""
Draft a professional, warm, and clear outreach message to a {target} for:
Community: {community_type}
Event: {event_name}
Additional Details: {details or "None"}

Please write a ready-to-send template with placeholders like [Speaker Name] or [Sponsor Contact] and include:
- Value proposition of speaking/sponsoring at this tech event
- Event date, format, and audience size
- Call to action (next steps)
    """
    result = await sampling.create_message(
        messages=[{"role": "user", "content": {"type": "text", "text": prompt}}],
        max_tokens=800,
        system_prompt="You are a warm community organizer. Write a highly engaging, persuasive, and professional outreach message.",
        metadata={"executa_invoke_id": invoke_id, "tool": "draft_comms"},
        timeout=60.0,
    )
    return {"result": result.get("content", {}).get("text", "")}

async def handle_assess_risks(community_type: str, event_name: str, details: str, invoke_id: str) -> dict:
    prompt = f"""
Perform a Risk Assessment and Readiness Scoring for:
Community: {community_type}
Event: {event_name}
Additional Details: {details or "None"}

Analyze potential failure modes (e.g. low SVPs, AV failures, speaker dropouts, food/beverage delays) and score the event's readiness.

Reply with a JSON object containing:
1. "score": An integer from 0 to 100 representing the Event Readiness Score based on the provided details (higher means more prepared/detailed inputs).
2. "risks": A list of 3-5 risks with "category", "description", and "mitigation".
3. "summary": A one-paragraph summary of the assessment.
    """
    
    schema = {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "description": "Readiness score out of 100"},
            "summary": {"type": "string", "description": "Brief assessment summary"},
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "mitigation": {"type": "string"}
                    },
                    "required": ["category", "description", "mitigation"]
                }
            }
        },
        "required": ["score", "summary", "risks"],
        "additionalProperties": False
    }

    result = await sampling.create_message(
        messages=[{"role": "user", "content": {"type": "text", "text": prompt}}],
        max_tokens=1000,
        system_prompt="You are a precise, analytical risk-mitigation expert for events. Reply with JSON only.",
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "risk_assessment",
                "strict": True,
                "schema": schema,
            },
        },
        on_unsupported="json_object",
        metadata={"executa_invoke_id": invoke_id, "tool": "assess_risks"},
        timeout=60.0,
    )

    raw = result.get("content", {}).get("text", "")
    try:
        data = json.loads(raw)
        # Format a human-readable result to display alongside the score
        formatted_text = f"### Event Readiness Score: {data.get('score', 0)}%\n\n"
        formatted_text += f"**Summary:** {data.get('summary', '')}\n\n"
        formatted_text += "### Key Risks & Mitigations:\n"
        for idx, r in enumerate(data.get("risks", [])):
            formatted_text += f"{idx+1}. [{r.get('category', 'Risk')}] {r.get('description', '')}\n"
            formatted_text += f"   *Mitigation:* {r.get('mitigation', '')}\n"
        
        return {
            "score": data.get("score", 50),
            "result": formatted_text
        }
    except Exception:
        return {"score": 50, "result": raw}

# --- JSON-RPC Dispatch -----------------------------------------------

def _make_response(req_id, *, result=None, error=None) -> dict:
    out = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out

def _handle_initialize(req_id, params: dict) -> dict:
    proto = (params or {}).get("protocolVersion") or "1.1"
    if proto != PROTOCOL_VERSION_V2:
        sampling.disable("host did not negotiate v2 protocol; sampling unavailable.")
    return _make_response(
        req_id,
        result={
            "protocolVersion": proto if proto in ("1.1", "2.0") else "2.0",
            "serverInfo": {
                "name": MANIFEST["display_name"],
                "version": MANIFEST["version"],
            },
            "client_capabilities": {"sampling": {}} if proto == PROTOCOL_VERSION_V2 else {},
            "capabilities": {},
        },
    )

_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()

def _handle_invoke(req_id, params: dict) -> dict:
    tool = params.get("tool")
    args = params.get("arguments") or {}
    invoke_id = params.get("invoke_id") or ""

    if tool != "communityops":
        return _make_response(
            req_id,
            error={"code": -32601, "message": f"Unknown tool: {tool}"},
        )

    action = args.get("action")
    community_type = args.get("community_type", "GDG")
    event_name = args.get("event_name", "Tech Meetup")
    details = args.get("details", "")
    comms_type = args.get("comms_type", "speaker")

    if action == "generate_plan":
        data = handle_generate_plan(community_type, event_name, details, invoke_id)
        return _make_response(req_id, result={"success": True, "tool": tool, "data": data})
    elif action == "generate_checklist":
        coro = handle_generate_checklist(community_type, event_name, details, invoke_id)
    elif action == "draft_comms":
        coro = handle_draft_comms(community_type, event_name, details, comms_type, invoke_id)
    elif action == "assess_risks":
        coro = handle_assess_risks(community_type, event_name, details, invoke_id)
    else:
        return _make_response(
            req_id,
            error={"code": -32602, "message": f"Unknown action: {action}"},
        )

    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        data = fut.result(timeout=120.0)
    except SamplingError as e:
        return _make_response(
            req_id,
            error={"code": e.code, "message": e.message, "data": e.data},
        )
    except Exception as e:
        return _make_response(
            req_id,
            error={"code": -32603, "message": f"Tool execution failed: {e}"},
        )
    return _make_response(req_id, result={"success": True, "tool": tool, "data": data})

def _handle_message(line: str) -> None:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        _write_frame(_make_response(None, error={"code": -32700, "message": "Parse error"}))
        return

    if "method" not in msg:
        if not sampling.dispatch_response(msg):
            print(f"Unmatched response id={msg.get('id')!r}", file=sys.stderr)
        return

    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        resp = _handle_initialize(req_id, params)
    elif method == "describe":
        resp = _make_response(req_id, result=MANIFEST)
    elif method == "invoke":
        resp = _handle_invoke(req_id, params)
    elif method == "health":
        resp = _make_response(req_id, result={"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})
    elif method == "shutdown":
        resp = _make_response(req_id, result={"ok": True})
    else:
        resp = _make_response(req_id, error={"code": -32601, "message": f"Method not found: {method}"})

    if req_id is not None:
        _write_frame(resp)

def main() -> None:
    print("CommunityOps Tool plugin started", file=sys.stderr)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="invoke")
    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            pool.submit(_handle_message, line)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        _loop.call_soon_threadsafe(_loop.stop)

if __name__ == "__main__":
    main()
