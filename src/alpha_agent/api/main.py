from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
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
from alpha_agent.infra.db.database import init_db, SessionLocal
from alpha_agent.infra.db.models import AgentAnalysisSession, AgentAuditLog
from alpha_agent.utils.logger import logger
import json
import time


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[api] 启动投资分析 API 服务...")
    try:
        init_db()
        logger.info("[api] 数据库初始化完成")
    except Exception as e:
        logger.warning(f"[api] 数据库初始化失败（将以无DB模式运行）: {e}")
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


@app.post("/api/chat/stream", tags=["对话"])
async def chat_stream(req: ChatRequest):
    import asyncio
    from langchain_core.messages import AIMessageChunk, ToolMessage

    start_time = time.time()

    db = SessionLocal()
    try:
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
        db.rollback()

    def _save_audit_log(log_type, event_type, **kwargs):
        try:
            log = AgentAuditLog(
                session_id=req.thread_id,
                log_type=log_type,
                event_type=event_type,
                worker_name=kwargs.get("worker_name", ""),
                worker_display_name=kwargs.get("display_name", ""),
                worker_icon=kwargs.get("icon", ""),
                worker_color=kwargs.get("color", ""),
                content=kwargs.get("content", ""),
                content_preview=kwargs.get("content", "")[:500],
                metadata_=kwargs.get("metadata", {}),
                step_number=kwargs.get("step_number", 0),
                round_number=kwargs.get("round_number", 0),
                status=kwargs.get("status", "info"),
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.warning(f"[api] 写入审计日志失败: {e}")
            db.rollback()

    def _update_session(**kwargs):
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

            yield _sse_event("start", {"thread_id": req.thread_id, "mode": "agent_loop"})
            _save_audit_log("system", "start", content="AgentLoop 分析开始", status="info")

            final_content = ""
            tool_calls_all = []
            step_counter = 0

            async for chunk in agent_loop.astream(req.message, session_id=req.thread_id):
                if "messages" in chunk and chunk["messages"]:
                    last_msg = chunk["messages"][-1]

                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        step_counter += 1
                        for tc in last_msg.tool_calls:
                            tool_name = tc.get("name", "")
                            tool_calls_all.append(tool_name)
                            _save_audit_log(
                                "tool", "tool_call",
                                content=f"调用工具: {tool_name}",
                                step_number=step_counter,
                                status="tool_call",
                                metadata={"name": tool_name, "args": tc.get("args", {})},
                            )
                            yield _sse_event("tool_call", {
                                "id": tc.get("id", ""),
                                "name": tool_name,
                                "args": tc.get("args", {}),
                            })

                    elif last_msg.type == "ai" and last_msg.content:
                        content = last_msg.content
                        if content and isinstance(content, str):
                            final_content = content
                            yield _sse_event("token", {"content": content})

                    elif last_msg.type == "tool":
                        yield _sse_event("tool_result", {"status": "completed"})

            duration_ms = int((time.time() - start_time) * 1000)
            _update_session(status="completed", total_duration_ms=duration_ms, final_result=final_content, total_steps=step_counter)
            _save_audit_log("system", "done", content=f"分析完成，耗时 {duration_ms}ms，共 {step_counter} 步", status="success")
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
        logger.error(f"[api] 获取对话列表失败: {e}")
        return ConversationListResponse(items=[])
    finally:
        db.close()


@app.get("/api/conversations/{session_id}", tags=["对话历史"], response_model=ConversationDetailResponse)
def get_conversation(session_id: str):
    db = SessionLocal()
    try:
        session = db.query(AgentAnalysisSession).filter_by(session_id=session_id).first()
        if not session:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="对话不存在")

        logs = (
            db.query(AgentAuditLog)
            .filter_by(session_id=session_id)
            .order_by(AgentAuditLog.created_at)
            .all()
        )
        messages = []
        for log in logs:
            messages.append(ConversationMessage(
                type=log.event_type,
                worker_name=log.worker_name or "",
                worker_display_name=log.worker_display_name or "",
                content=log.content or "",
                step_number=log.step_number or 0,
                timestamp=log.created_at.isoformat() if log.created_at else "",
            ))

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
    except Exception as e:
        logger.error(f"[api] 获取对话详情失败: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.delete("/api/conversations/{session_id}", tags=["对话历史"])
def delete_conversation(session_id: str):
    db = SessionLocal()
    try:
        session = db.query(AgentAnalysisSession).filter_by(session_id=session_id).first()
        if session:
            db.delete(session)
            db.query(AgentAuditLog).filter_by(session_id=session_id).delete()
            db.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"[api] 删除对话失败: {e}")
        db.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/api/tracer/stats", tags=["追踪"])
async def get_tracer_stats(days: int = 7):
    from alpha_agent.utils.tracer import get_tracer
    tracer = get_tracer()
    return tracer.get_stats(days=days)


@app.get("/api/tracer/traces", tags=["追踪"])
async def get_tracer_traces(limit: int = 50):
    from alpha_agent.utils.tracer import get_tracer
    tracer = get_tracer()
    return {"traces": tracer.get_recent_traces(limit=limit)}