from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from alpha_agent.config import __version__
from alpha_agent.api.schemas import (
    ChatRequest,
    ConversationItem,
    ConversationListResponse,
    ConversationDetailResponse,
    ConversationMessage,
)
from alpha_agent.infra.db.database import init_db, SessionLocal, is_db_available
from alpha_agent.infra.db.models import AgentAnalysisSession, AgentAuditLog
from alpha_agent.utils.logger import logger
import asyncio
import json
import time

from langchain_core.messages import AIMessageChunk, ToolMessage


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[api] 启动投资分析 API 服务...")
    if is_db_available():
        try:
            init_db()
            logger.info("[api] 数据库初始化完成")
        except Exception as e:
            logger.warning(f"[api] 数据库初始化失败（将以无DB模式运行）: {e}")
    else:
        logger.warning("[api] 数据库不可用，以无DB模式运行（历史对话将不会持久化）")
    logger.info(f"[api] 服务启动完成，版本: {__version__}")
    yield
    logger.info("[api] 服务关闭")


app = FastAPI(
    title="投资分析 Agent API",
    description="基于 AgentLoop 的投资分析智能体",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/health", tags=["系统"])
async def health():
    status = {"status": "ok", "components": {}}

    try:
        from alpha_agent.infra.llm import get_llm_service
        llm_svc = get_llm_service()
        status["components"]["llm"] = "enabled" if llm_svc.enabled else "disabled"
    except Exception as e:
        status["components"]["llm"] = f"error: {e}"

    if is_db_available():
        try:
            from sqlalchemy import text
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            db.close()
            status["components"]["database"] = "connected"
        except Exception as e:
            status["components"]["database"] = f"error: {e}"
    else:
        status["components"]["database"] = "disabled (no-db mode)"

    try:
        from alpha_agent.infra.process_registry import _registry
        active = len([t for t in _registry._tasks.values()
                      if t.status.value == "running"])
        status["components"]["process_registry"] = {
            "active_tasks": active,
            "total_tasks": len(_registry._tasks),
        }
    except Exception:
        status["components"]["process_registry"] = "unavailable"

    return status


@app.post("/api/chat/stream", tags=["对话"])
async def chat_stream(req: ChatRequest):
    start_time = time.time()

    db = None
    if is_db_available():
        try:
            db = SessionLocal()
            session = AgentAnalysisSession(
                session_id=req.thread_id,
                user_query=req.message,
                analysis_type="agent_loop",
                status="running",
            )
            db.add(session)
            db.commit()
        except Exception as e:
            logger.warning(f"[api] 创建分析会话失败: {e}")
            if db is not None:
                db.rollback()

    def _save_audit_log(log_type, event_type, *, content="", status="info", step_number=0, metadata=None):
        if db is None:
            return
        try:
            log = AgentAuditLog(
                session_id=req.thread_id,
                log_type=log_type,
                event_type=event_type,
                content=content,
                content_preview=content[:500],
                metadata_=metadata or {},
                step_number=step_number,
                status=status,
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.warning(f"[api] 写入审计日志失败: {e}")
            db.rollback()

    def _update_session(**kwargs):
        if db is None:
            return
        try:
            session = db.query(AgentAnalysisSession).filter_by(session_id=req.thread_id).first()
            if session:
                for k, v in kwargs.items():
                    setattr(session, k, v)
                db.commit()
        except Exception as e:
            logger.warning(f"[api] 更新会话失败: {e}")
            db.rollback()

    async def generate() -> AsyncGenerator[str, None]:
        try:
            from alpha_agent.core.agent_loop import get_agent_loop

            agent_loop = get_agent_loop()

            yield _sse_event("start", {"thread_id": req.thread_id})
            await asyncio.to_thread(
                _save_audit_log, "system", "start",
                content="AgentLoop 分析开始", status="info",
            )

            final_content = ""
            tool_calls_all = []
            step_counter = 0
            sent_tool_call_ids: set[str] = set()

            async for chunk in agent_loop.astream(req.message, session_id=req.thread_id):
                if chunk["mode"] == "messages":
                    msg = chunk["message"]

                    if isinstance(msg, AIMessageChunk) and msg.content:
                        if isinstance(msg.content, str) and msg.content:
                            yield _sse_event("token", {"content": msg.content})

                    elif isinstance(msg, ToolMessage):
                        yield _sse_event("tool_result", {"status": "completed"})

                elif chunk["mode"] == "values":
                    state = chunk["state"]
                    step_counter = state.get("step_count", step_counter)
                    messages = state.get("messages", [])

                    if messages:
                        last_msg = messages[-1]

                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            for tc in last_msg.tool_calls:
                                tc_id = tc.get("id", "")
                                if tc_id and tc_id in sent_tool_call_ids:
                                    continue
                                sent_tool_call_ids.add(tc_id)
                                tool_name = tc.get("name", "")
                                tool_calls_all.append(tool_name)
                                step_counter += 1
                                await asyncio.to_thread(
                                    _save_audit_log,
                                    "tool", "tool_call",
                                    content=f"调用工具: {tool_name}",
                                    step_number=step_counter,
                                    status="tool_call",
                                    metadata={"name": tool_name, "args": tc.get("args", {})},
                                )
                                yield _sse_event("tool_call", {
                                    "id": tc_id,
                                    "name": tool_name,
                                    "args": tc.get("args", {}),
                                })

                        elif last_msg.type == "ai" and last_msg.content:
                            if isinstance(last_msg.content, str):
                                final_content = last_msg.content

            duration_ms = int((time.time() - start_time) * 1000)
            await asyncio.to_thread(
                _update_session,
                status="completed", total_duration_ms=duration_ms,
                final_result=final_content, total_steps=step_counter,
            )
            await asyncio.to_thread(
                _save_audit_log, "system", "done",
                content=f"分析完成，耗时 {duration_ms}ms，共 {step_counter} 步",
                status="success",
            )
            yield _sse_event("done", {
                "thread_id": req.thread_id,
                "response": final_content,
                "tool_calls": tool_calls_all,
                "duration_ms": duration_ms,
                "steps": step_counter,
            })

        except Exception as e:
            logger.error(f"[api] 流式对话失败: {e}")
            yield _sse_event("error", {"message": str(e)})
        finally:
            if db is not None:
                db.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/conversations", tags=["对话历史"], response_model=ConversationListResponse)
def list_conversations():
    if not is_db_available():
        return ConversationListResponse(items=[])
    db = SessionLocal()
    try:
        sessions = (
            db.query(AgentAnalysisSession)
            .order_by(AgentAnalysisSession.created_at.desc())
            .limit(50)
            .all()
        )
        items = []
        for s in sessions:
            items.append(ConversationItem(
                session_id=s.session_id,
                user_query=s.user_query[:60] if s.user_query else "",
                analysis_type=s.analysis_type,
                status=s.status,
                created_at=s.created_at.isoformat() if s.created_at else "",
                duration_ms=s.total_duration_ms or 0,
                total_steps=s.total_steps or 0,
            ))
        return ConversationListResponse(items=items)
    except Exception as e:
        logger.warning(f"[api] 获取对话列表失败: {e}")
        return ConversationListResponse(items=[])
    finally:
        db.close()


@app.get("/api/conversations/{session_id}", tags=["对话历史"], response_model=ConversationDetailResponse)
def get_conversation(session_id: str):
    if not is_db_available():
        raise HTTPException(status_code=404, detail="当前为无DB模式，无历史对话")
    db = SessionLocal()
    try:
        session = db.query(AgentAnalysisSession).filter_by(session_id=session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="对话不存在")

        messages = [
            ConversationMessage(role="user", content=session.user_query or ""),
            ConversationMessage(role="assistant", content=session.final_result or ""),
        ]

        return ConversationDetailResponse(
            session_id=session.session_id,
            user_query=session.user_query or "",
            analysis_type=session.analysis_type or "",
            status=session.status or "",
            final_result=session.final_result or "",
            created_at=session.created_at.isoformat() if session.created_at else "",
            duration_ms=session.total_duration_ms or 0,
            total_steps=session.total_steps or 0,
            messages=messages,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[api] 获取对话详情失败: {e}")
        raise HTTPException(status_code=404, detail="对话不存在")
    finally:
        db.close()


@app.delete("/api/conversations/{session_id}", tags=["对话历史"])
def delete_conversation(session_id: str):
    if not is_db_available():
        return {"status": "ok"}
    db = SessionLocal()
    try:
        session = db.query(AgentAnalysisSession).filter_by(session_id=session_id).first()
        if session:
            db.delete(session)
            db.query(AgentAuditLog).filter_by(session_id=session_id).delete()
            db.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.warning(f"[api] 删除对话失败: {e}")
        db.rollback()
        return {"status": "ok"}
    finally:
        db.close()


@app.post("/api/clarify/respond", tags=["对话"])
async def clarify_respond(session_id: str, response: str):
    from alpha_agent.tools.core.clarify_tool import CLARIFY_RESPONSES

    if session_id in CLARIFY_RESPONSES:
        CLARIFY_RESPONSES[session_id]["response"] = response
        CLARIFY_RESPONSES[session_id]["event"].set()
        return {"status": "ok"}
    return {"status": "not_found", "message": "没有待处理的 clarify 请求"}


@app.post("/api/approve/command", tags=["审批"])
async def approve_command(session_id: str, command: str, approved: bool = True):
    from alpha_agent.core.approval import APPROVAL_PENDING
    key = f"{session_id}:{command}"
    if key in APPROVAL_PENDING:
        APPROVAL_PENDING[key] = approved
        return {"status": "ok", "approved": approved, "command": command}
    return {"status": "not_found", "message": "没有待审批的命令"}


@app.get("/api/approve/config", tags=["审批"])
async def get_approval_config():
    from alpha_agent.core.approval import ApprovalMode
    return {
        "modes": [m.value for m in ApprovalMode],
        "current": "smart",
        "hardline_patterns_count": 0,
        "dangerous_patterns_count": 0,
    }


@app.post("/api/interrupt/{session_id}", tags=["对话"])
async def interrupt_session(session_id: str):
    from alpha_agent.core.interrupt import set_interrupt
    from alpha_agent.core.agent_loop import get_agent_loop
    try:
        agent_loop = get_agent_loop()
        set_interrupt(True)
        return {"status": "interrupted", "session_id": session_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/tracer/stats", tags=["追踪"])
async def get_tracer_stats(days: int = 7):
    from alpha_agent.utils.tracer import get_tracer
    tracer = get_tracer()
    return tracer.get_stats(days=days)


@app.get("/api/tracer/traces", tags=["追踪"])
async def get_tracer_traces(limit: int = 50):
    from alpha_agent.utils.tracer import get_tracer
    tracer = get_tracer()