from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from collections import deque
import logging
import os
from dotenv import load_dotenv
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
from difflib import SequenceMatcher

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
# Logging
# ==========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

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
                    topic TEXT,
                    session_id TEXT
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
    stars: Optional[int] = None 

# ==========================
# Conversational State
# ==========================
MAX_HISTORY = 20
conversation_states = {}

def get_initial_state():
    return {
        "history": deque(maxlen=MAX_HISTORY),
        "current_topic": None,
        "objective": "Dar respuestas didácticas y visuales",
        "has_introduced": False
    }

# ==========================
# Clasificación de intención
# ==========================
def classify_intent(message: str) -> str:
    keywords = ["recurso", "material", "documento"]
    if any(k in message.lower() for k in keywords):
        return "provide_resource"
    return "general"

# ==========================
# Construcción de prompts
# ==========================
def build_prompts(state, user_message):
    base_prompt = f"""
Sos Aimi, un asistente experto en dar respuestas didácticas y visuales. 
Respondé de manera clara y completa:

- Resaltá lo más importante en negrita.
- Enumerá puntos clave con viñetas.
- Separá en secciones si hay distintos temas.
- Al final, incluí un pequeño resumen con lo más relevante.

Pregunta: {user_message}

Respuesta:
"""
    system_prompt = f"""Sos Aimi.
Objetivo: {state['objective']}
Tema actual: {state['current_topic']}

Reglas estrictas:
- No te reinicies.
- No te presentes otra vez.
- No preguntes "¿en qué te ayudo?" si el usuario aportó información.
- Continuá el hilo de la conversación.
- Respondé de forma directa y útil.

{base_prompt}
"""
    return system_prompt

# ==========================
# Detección de preguntas similares
# ==========================
def is_similar(a: str, b: str, threshold: float = 0.8) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold

def save_interaction_unique(session_id: str, question: str, answer: str, topic: str):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Traer últimas interacciones de esta sesión
                cur.execute(
                    "SELECT id, question FROM interactions WHERE session_id = %s ORDER BY id DESC LIMIT 20;",
                    (session_id,)
                )
                rows = cur.fetchall()

                # Revisar similitud
                for row in rows:
                    if is_similar(question, row['question']):
                        logging.info(f"Pregunta similar detectada, se omite guardado: {question}")
                        return row['id']  # devolver id existente

                # Guardar nueva interacción
                cur.execute(
                    """
                    INSERT INTO interactions (question, answer, session_id, topic)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (question, answer, session_id, topic)
                )
                conn.commit()
                return cur.fetchone()['id']
    except Exception as e:
        logging.error(f"Error al guardar interacción: {e}")
        return None

# ==========================
# Endpoint /chat
# ==========================
@app.post("/chat")
async def chat(msg: Message):
    if not msg.session_id or not msg.message:
        raise HTTPException(status_code=400, detail="Faltan session_id o message")

    state = conversation_states.get(msg.session_id)
    if not state:
        state = get_initial_state()
        conversation_states[msg.session_id] = state

    intent = classify_intent(msg.message)
    state["current_topic"] = "resource" if intent == "provide_resource" else "general"

    system_prompt = build_prompts(state, msg.message)
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
        logging.error(f"Error al generar respuesta: {e}")
        raise HTTPException(status_code=500, detail="Error al generar respuesta AI")

    # Actualizar historial
    state["history"].append({"role": "user", "content": msg.message})
    state["history"].append({"role": "assistant", "content": answer})
    state["has_introduced"] = True

    # Guardado inteligente
    interaction_id = save_interaction_unique(
        session_id=msg.session_id,
        question=msg.message,
        answer=answer,
        topic=state["current_topic"]
    )

    return {"answer": answer, "source": "ai", "interaction_id": interaction_id}

# ==========================
# GET INTERACTIONS
# ==========================
@app.get("/interactions")
async def get_interactions():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM interactions
                ORDER BY id DESC;
            """)
            return cur.fetchall()


# =========================
# VERIFIER VOTING
# =========================
@app.post("/vote/verifier")
async def vote_verifier(v: Vote):
    with get_db() as conn:
        with conn.cursor() as cur:

            if v.stars == 1:
                # ❌ borrar definitivamente
                cur.execute("""
                    DELETE FROM interactions
                    WHERE id = %s;
                """, (v.interaction_id,))

            elif v.stars == 2:
                # 🔄 sigue en verificador
                cur.execute("""
                    UPDATE interactions
                    SET status = 'pending'
                    WHERE id = %s;
                """, (v.interaction_id,))

            elif v.stars == 3:
                # ➡️ pasa a experto
                cur.execute("""
                    UPDATE interactions
                    SET status = 'expert_pending'
                    WHERE id = %s;
                """, (v.interaction_id,))

            conn.commit()

    return {"ok": True}


# ==========================
# EXPERT APPROVE
# ==========================
@app.post("/expert/approve")
async def expert_approve(v: Vote):
    if not v.interaction_id:
        raise HTTPException(status_code=400, detail="interaction_id es obligatorio")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE interactions
                SET status = 'operator_pending'
                WHERE id = %s;
            """, (v.interaction_id,))                        
            conn.commit()
    return {"ok": True}

# =========================
# EXPERT REJECT
# =========================
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


# =========================
# OPERATOR APPROVE + TOPIC
# =========================
class OperatorApprove(BaseModel):
    interaction_id: int
    topic: str

@app.post("/operator/approve")
async def operator_approve(a: OperatorApprove):
    if not a.interaction_id or not a.topic:
        raise HTTPException(status_code=400, detail="interaction_id y topic son obligatorios")
    
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE interactions
                    SET status = 'stored', topic = %s
                    WHERE id = %s;
                """, (a.topic, a.interaction_id))
                conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar interacción: {e}")

    return {"ok": True}

import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

class GenerateTopicRequest(BaseModel):
    prompt: str

@app.post("/openai/generate_topic")
async def generate_topic(req: GenerateTopicRequest):
    """
    Recibe un prompt con la interacción (pregunta + respuesta)
    y devuelve un topic breve (1-3 palabras) para la conversación.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # o gpt-4 si tienes acceso
            messages=[
                {"role": "system", "content": "Eres un generador de topics breves para interacciones de chat."},
                {"role": "user", "content": req.prompt}
            ],
            temperature=0.5,
            max_tokens=10  # solo queremos un topic muy breve
        )

        topic_text = response.choices[0].message.content.strip()
        topic_words = topic_text.split()
        topic_clean = " ".join(topic_words[:3])  # 1-3 palabras

        return {"topic": topic_clean}

    except Exception as e:
        print("Error generando topic con OpenAI:", e)
        return {"topic": "general"}  # fallback con logs