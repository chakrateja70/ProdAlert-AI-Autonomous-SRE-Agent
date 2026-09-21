import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from src.config import config
from src.graph import app_graph

app = FastAPI(title="ProdAlert-AI")

# Langfuse tracing enable (optional but powerful)
langfuse_handler = None
try:
    from langfuse.langchain import CallbackHandler

    if config.LANGFUSE_SECRET_KEY and config.LANGFUSE_PUBLIC_KEY:
        # CallbackHandler reads LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY / LANGFUSE_HOST
        # from the environment itself; config.py's load_dotenv() already put them there.
        langfuse_handler = CallbackHandler()
except ImportError:
    pass

print("✅ Langfuse tracing enabled" if langfuse_handler else "⚠️ Langfuse not configured, running without tracing")

class AlertInput(BaseModel):
    message: str

@app.get("/")
def health():
    return {"status": "ProdAlert-AI is running", "version": "v1"}

@app.post("/alert")
def handle_alert(payload: AlertInput):
    print(f"🚨 Alert received: {payload.message}")

    run_config = {"callbacks": [langfuse_handler]} if langfuse_handler else {}

    result = app_graph.invoke({
        "alert": payload.message,
        "retries": 0,
        "confidence": 0.0,
        "triage_decision": "",
        "investigation_report": ""
    }, config=run_config)
    
    return {
        "triage_decision": result.get("triage_decision"),
        "confidence": result.get("confidence"),
        "report": result.get("investigation_report")
    }

# CLI kosam kuda work avvali
if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)