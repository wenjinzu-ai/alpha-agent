"""启动 FastAPI 服务：
    python -m alpha_agent.api
    uvicorn alpha_agent.api.main:app --host 0.0.0.0 --port 8001 --reload
"""
import uvicorn


def main():
    uvicorn.run(
        "alpha_agent.api.main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
    )


if __name__ == "__main__":
    main()