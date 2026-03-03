from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, math, json
from dotenv import load_dotenv
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor

# ==========================
# Configuración
# ==========================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="Aimi Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# DB Connection
# ==========================
def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ==========================
# DB Init
# ==========================
def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id SERIAL PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    verifier_votes INT[] DEFAULT '{}',
                    expert_votes INT[] DEFAULT '{}',
                    status TEXT DEFAULT 'pending',
                    topic TEXT
                );
            """)
            conn.commit()

init_db()

# ==========================
# Models
# ==========================
class Message(BaseModel):
    message: str

class Vote(BaseModel):
    interaction_id: int
    stars: int

class Approve(BaseModel):
    interaction_id: int
    topic: str

# ==========================
# Embeddings (opcional)
# ==========================
def embedding(text):
    return client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    ).data[0].embedding

def cosine(a, b):
    return sum(x*y for x,y in zip(a,b)) / (
        math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(y*y for y in b))
    )

# ==========================
# Endpoints
# ==========================
@app.post("/chat")
async def chat(msg: Message):
    # Revisar si la pregunta ya existe en DB
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT answer FROM interactions WHERE question=%s LIMIT 1;", (msg.message,))
            row = cur.fetchone()
            if row:
                return {"answer": row['answer'], "source": "db"}

    # Si no existe, llamar a OpenAI
    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu nombre es Aimi. "
                        "Siempre debés presentarte como Aimi cuando te pregunten tu nombre. "
                        "Sos una asistente inteligente en aprendizaje, creada como un proyecto colaborativo. "
                        "Nunca digas que sos ChatGPT ni menciones OpenAI."
                    )
                },
                {"role": "user", "content": msg.message}
            ]
        )
        answer = completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Guardar en DB
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interactions (question, answer)
                VALUES (%s, %s)
                RETURNING *;
                """,
                (msg.message, answer)
            )
            interaction = cur.fetchone()
            conn.commit()

    return {"answer": answer, "source": "ai"}

@app.get("/interactions")
async def get_interactions():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM interactions ORDER BY id DESC;")
            return cur.fetchall()

@app.post("/vote/verifier")
async def vote_verifier(v: Vote):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE interactions
                SET verifier_votes = array_append(verifier_votes, %s),
                    status = CASE
                        WHEN array_length(array_append(verifier_votes, %s), 1) > 0
                        THEN 'verified'
                        ELSE status
                    END
                WHERE id = %s;
            """, (v.stars, v.stars, v.interaction_id))
            conn.commit()
    return {"ok": True}

@app.post("/vote/expert")
async def vote_expert(v: Vote):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE interactions
                SET expert_votes = array_append(expert_votes, %s),
                    status = CASE
                        WHEN array_length(array_append(expert_votes, %s), 1) > 0
                        THEN 'expert_approved'
                        ELSE status
                    END
                WHERE id = %s;
            """, (v.stars, v.stars, v.interaction_id))
            conn.commit()
    return {"ok": True}

@app.post("/operator/approve")
async def approve(a: Approve):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE interactions
                SET status = 'stored',
                    topic = %s
                WHERE id = %s;
            """, (a.topic, a.interaction_id))
            conn.commit()
    return {"stored": True}