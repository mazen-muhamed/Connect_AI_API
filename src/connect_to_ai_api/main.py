from fastapi import FastAPI
from connect_to_ai_api.routers.triage import router as triage_router

app = FastAPI()
app.include_router(triage_router)