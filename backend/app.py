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
# Endpoint /chat
# ==========================
@app.post("/chat")
async def chat(msg: Message):
    # Validar entrada
    if not msg.session_id or not msg.message:
        raise HTTPException(status_code=400, detail="Faltan session_id o message")

    # Obtener o crear estado por sesión
    state = conversation_states.get(msg.session_id)
    if not state:
        state = get_initial_state()
        conversation_states[msg.session_id] = state

    # Clasificar intención
    intent = classify_intent(msg.message)
    state["current_topic"] = "resource" if intent == "provide_resource" else "general"

    # Construir prompt
    system_prompt = build_prompts(state, msg.message)

    # Preparar mensajes para el modelo
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(state["history"])
    messages.append({"role": "user", "content": msg.message})

    # Llamada al modelo
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

    # Guardar en base de datos
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO interactions (question, answer, session_id, topic)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (msg.message, answer, msg.session_id, state["current_topic"])
                )
                conn.commit()
    except Exception as db_e:
        logging.error(f"Error al guardar en DB: {db_e}")

    return {"answer": answer, "source": "ai"}

# =========================
# GET INTERACTIONS
# =========================
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