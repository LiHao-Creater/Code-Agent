import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from agent_engine import workflow_orchestrator

app = FastAPI()

# 允许 React 前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TaskRequest(BaseModel):
    task: str


@app.post("/generate")
async def generate_stream(request: TaskRequest):
    async def event_generator():
        # 获取 Agent 产生的数据流
        async for event_data in workflow_orchestrator(request.task):
            # SSE 格式: data: <json_string>\n\n
            yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)