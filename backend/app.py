from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
    stars: Optional[int] = None 

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
# ==========================
# AUTO FORMAT CODE
# ==========================
import re
import textwrap

def auto_format_code(text: str) -> str:
    """
    Detecta automáticamente si el texto contiene código y cuál es el lenguaje.
    Envuelve en bloques Markdown ``` con el lenguaje detectado.
    Intenta mejorar indentación para Python y JS.
    """
    if "```" in text:
        return text  # Ya está formateado

    # Diccionario de patrones por lenguaje
    code_patterns = {
        "python": [
            r"\bdef\s+\w+\(",
            r"\bclass\s+\w+",
            r"\breturn\s+",
            r"print\(",
            r"\bfor\s+\w+\s+in\s+",
            r"\bif\s+.*:",
            r"\belif\b",
            r"\bimport\b"
        ],
        "javascript": [
            r"function\s+\w+\(",
            r"console\.log\(",
            r"{.*}",
            r";$",
            r"\bconst\b",
            r"\blet\b",
            r"\bvar\b",
        ],
        "java": [
            r"public\s+class\s+\w+",
            r"System\.out\.println\(",
        ],
        "c": [
            r"#include\s+<.*>",
            r"printf\(",
            r"int\s+main\s*\(",
        ],
        "cpp": [
            r"#include\s+<.*>",
            r"std::cout",
            r"int\s+main\s*\(",
        ],
        "bash": [
            r"#!/bin/bash",
            r"echo\s+",
            r"\$[a-zA-Z_]+"
        ],
        "html": [
            r"<!DOCTYPE html>",
            r"<html.*>",
            r"<head>",
            r"<body>"
        ],
        "css": [
            r"\{.*\}",
            r"[.#]?[a-zA-Z0-9_-]+\s*\{"
        ],
        "sql": [
            r"\bSELECT\b",
            r"\bINSERT\b",
            r"\bUPDATE\b",
            r"\bDELETE\b",
            r"\bFROM\b",
            r"\bWHERE\b"
        ]
    }

    detected_language = None
    for lang, patterns in code_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                detected_language = lang
                break
        if detected_language:
            break

    if detected_language:
        lines = text.splitlines()
        cleaned_lines = [line.rstrip() for line in lines if line.strip() != ""]
        cleaned_text = "\n".join(cleaned_lines)

        if detected_language in ["python", "javascript"]:
            cleaned_text = textwrap.dedent(cleaned_text)

        return f"```{detected_language}\n{cleaned_text}\n```"

    return text


# ==========================
# ENDPOINT CHAT
# ==========================
@app.post("/chat")
async def chat(msg: Message):
    state = conversation_states.get(msg.session_id)
    if not state:
        state = get_initial_state()
        conversation_states[msg.session_id] = state

    intent = classify_intent(msg.message)
    if intent == "provide_resource":
        state["current_topic"] = "resource"

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

    # Post-procesado para código
    answer = auto_format_code(answer)

    # Actualizar historial
    state["history"].append({"role": "user", "content": msg.message})
    state["history"].append({"role": "assistant", "content": answer})

    if len(state["history"]) > MAX_HISTORY:
        state["history"] = state["history"][-MAX_HISTORY:]

    state["has_introduced"] = True

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
            conn.commit()

    return {"answer": answer, "source": "ai"}


# =========================
# GET INTERACTIONS
# =========================
@app.get("/interactions")
async def get_interactions():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, question, answer, status, topic
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

# =========================
# GENERAR TOPIC AUTOMÁTICO (OPERADOR)
# =========================
class GenerateTopicRequest(BaseModel):
    prompt: str


@app.post("/openai/generate_topic")
async def generate_topic(req: GenerateTopicRequest):

    try:

        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Genera un topic breve de 1 a 3 palabras."
                },
                {
                    "role": "user",
                    "content": req.prompt
                }
            ],
            max_tokens=10,
            temperature=0.5
        )

        topic_text = completion.choices[0].message.content.strip()

        topic_words = topic_text.split()
        topic_clean = " ".join(topic_words[:3])

        return {"topic": topic_clean}

    except Exception as e:

        print("Error generando topic:", e)

        return {"topic": "general"}
