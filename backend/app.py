from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
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
    session_id: str
    message: str

class Vote(BaseModel):
    interaction_id: int
    stars: int

class Approve(BaseModel):
    interaction_id: int
    topic: str

# ==========================
# Conversational State (MULTIUSUARIO)
# ==========================
conversation_states = {}
MAX_HISTORY = 6

def get_initial_state():
    return {
        "objective": "Asistir al usuario manteniendo coherencia conversacional",
        "current_topic": None,
        "has_introduced": False,
        "history": []
    }

# ==========================
# Clasificación de intención (simple)
# ==========================
def classify_intent(text: str) -> str:
    t = text.lower()
    if "http" in t or "github.com" in t:
        return "provide_resource"
    if t.startswith("como") or t.startswith("cómo"):
        return "ask_how"
    return "continue"

# ==========================
# Endpoints
# ==========================
@app.post("/chat")
async def chat(msg: Message):
    # Obtener o crear estado por sesión
    state = conversation_states.get(msg.session_id)
    if not state:
        state = get_initial_state()
        conversation_states[msg.session_id] = state

    # OPERADOR: clasificar intención antes del modelo
    intent = classify_intent(msg.message)
    if intent == "provide_resource":
        state["current_topic"] = "resource"

    # Prompt del operador
    system_prompt = f"""
Sos Aimi.
Objetivo: {state['objective']}
Tema actual: {state['current_topic']}

Reglas estrictas:
- No te reinicies.
- No te presentes otra vez.
- No preguntes "¿en qué te ayudo?" si el usuario aportó información.
- Continuá el hilo de la conversación.
- Respondé de forma directa y útil.
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(state["history"])
    messages.append({"role": "user", "content": msg.message})

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages
        )
        answer = completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Actualizar historial del usuario
    state["history"].append({"role": "user", "content": msg.message})
    state["history"].append({"role": "assistant", "content": answer})

    if len(state["history"]) > MAX_HISTORY:
        state["history"] = state["history"][-MAX_HISTORY:]

    state["has_introduced"] = True

    # Guardar interacción
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

            if v.stars == 1:
                # ❌ eliminar completamente del flujo
                cur.execute("""
                    UPDATE interactions
                    SET status = 'removed'
                    WHERE id = %s;
                """, (v.interaction_id,))

            elif v.stars == 2:
                # 🔄 sigue en verificador
                cur.execute("""
                    UPDATE interactions
                    SET verifier_votes = array_append(verifier_votes, %s),
                        status = 'pending'
                    WHERE id = %s;
                """, (v.stars, v.interaction_id))

            elif v.stars == 3:
                # ➡️ pasa a experto
                cur.execute("""
                    UPDATE interactions
                    SET verifier_votes = array_append(verifier_votes, %s),
                        status = 'expert_pending'
                    WHERE id = %s;
                """, (v.stars, v.interaction_id))

            conn.commit()

    return {"ok": True}

@app.post("/expert/approve")
async def expert_approve(v: Vote):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE interactions
                SET status = 'stored'
                WHERE id = %s;
            """, (v.interaction_id,))
            conn.commit()
    return {"ok": True}


@app.post("/expert/reject")
async def expert_reject(v: Vote):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE interactions
                SET status = 'removed'
                WHERE id = %s;
            """, (v.interaction_id,))
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