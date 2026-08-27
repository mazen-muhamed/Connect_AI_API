from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from src.connect_to_ai_api.schema import TriageOutput
from src.connect_to_ai_api.client import triage_message


router = APIRouter()

class TriageInput(BaseModel):
    text:str = Field(...,min_length=1, max_length=2000)
    
@router.post("/triage", response_model=TriageOutput)
async def triage(input: TriageInput):
    result = triage_message(input.text)
    return result
    