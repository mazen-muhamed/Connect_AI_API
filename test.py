import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Response
from typing import Optional, List
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Integration CRUD w SQL")

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ["DB_PORT"])
DB_USER = os.environ["DB_USER"]
DB_NAME = os.environ["DB_NAME"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INT AUTO_INCREMENT PRIMARY KEY,
                task_name VARCHAR(255) NOT NULL,
                task_description TEXT,
                task_status BOOLEAN NOT NULL DEFAULT false
            )
        """)
        conn.commit()

        cur.execute("SELECT COUNT(*) AS count FROM tasks")
        count = cur.fetchone()["count"]
        if count == 0:
            cur.executemany(
                "INSERT INTO tasks (task_name, task_description, task_status) VALUES (%s, %s, %s)",
                [
                    ("Buy Groceries", "2% from the store", False),
                    ("Make Assignment", "Make coding Assignment", True),
                    ("Study AI", "Build AI Agentic Model", False),
                ],
            )
            conn.commit()
    conn.close()


@app.on_event("startup")
def startup():
    init_db()


class CreateTask(BaseModel):
    task_name: str
    task_description: Optional[str] = None
    task_status: Optional[bool] = False


class TaskResponse(BaseModel):
    task_id: int
    task_name: str
    task_description: Optional[str] = None
    task_status: Optional[bool] = False

    class Config:
        from_attributes = True

                    #### EndPoints ###

@app.get('/health')
def health():
    return {"status": "OK"}


@app.get('/')
def root():
    return {"Message": "Intro to FastAPI w/ raw SQL"}


@app.get('/tasks', response_model=List[TaskResponse])
def get_all_tasks(db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM tasks")
        rows = cur.fetchall()
    return rows


@app.get('/tasks/{task_id}', response_model=TaskResponse)
def getTaskById(task_id: int, db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM tasks WHERE task_id = %s", (task_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return row


@app.post('/tasks', response_model=TaskResponse, status_code=201)
def createTask(task: CreateTask, db=Depends(get_db)):
    if not task.task_name.strip():
        raise HTTPException(status_code=400, detail="Task name required")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO tasks (task_name, task_description, task_status) VALUES (%s, %s, %s) RETURNING *",
            (task.task_name, task.task_description, task.task_status)
        )
        row = cur.fetchone()
        db.commit()
    return row


@app.put('/tasks/{task_id}', response_model=TaskResponse)
def updateTask(task_id: int, task: CreateTask, db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM tasks WHERE task_id = %s", (task_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task does not exist!")
        if not task.task_name.strip():
            raise HTTPException(status_code=400, detail="Task Name Required!")

        cur.execute(
            "UPDATE tasks SET task_name = %s, task_description = %s, task_status = %s WHERE task_id = %s",
            (task.task_name, task.task_description, task.task_status, task_id),
        )
        cur.execute("SELECT * FROM tasks WHERE task_id = %s", (task_id,))
        row = cur.fetchone()
        db.commit()
    return row


@app.delete('/tasks/{task_id}', status_code=204)
def deleteTask(task_id: int, db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM tasks WHERE task_id = %s", (task_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task does not exist!")

        cur.execute("DELETE FROM tasks WHERE task_id = %s", (task_id,))
        db.commit()
    return Response(status_code=204)