import os
from fastapi import FastAPI
from connect_to_ai_api.routers.triage import router as triage_router
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()



app = FastAPI()
app.include_router(triage_router)


client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],   
    api_key=os.environ["LLM_API_KEY"],     
)
res = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "user", "content": "Reply with exactly the word: ready"}],
    temperature=0,
)

print(res.choices[0].message.content)