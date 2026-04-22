from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from dotenv import load_dotenv
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
from urllib.parse import urlparse, urlunparse
import re
import textwrap
import requests


# ==========================
# Configuración
# ==========================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

print("OPENAI_API_KEY:", "OK" if OPENAI_API_KEY else "MISSING")
print("DATABASE_URL:", "OK" if DATABASE_URL else "MISSING")

app = FastAPI(title="Aimi Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# DB Connection
# ==========================
def get_db():
    print("DATABASE_URL:", DATABASE_URL)
    if not DATABASE_URL:
        raise Exception("DATABASE_URL no configurada")

    url = DATABASE_URL

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(
        url,
        cursor_factory=RealDictCursor,
        connect_timeout=10
    )

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

@app.on_event("startup")
def startup():
    try:
        init_db()
        print("✅ DB OK")
    except Exception as e:
        print("❌ DB INIT ERROR:", e)


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

def add_www_to_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc or parsed.path  # a veces el dominio está en path
    if not netloc.startswith("www.") and not netloc.startswith("localhost"):
        netloc = "www." + netloc
    # reconstruir URL
    return urlunparse(parsed._replace(netloc=netloc, path="" if parsed.netloc == "" else parsed.path))

def verify_url(url: str) -> bool:
    try:
        r = requests.head(url, timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False

def process_links_in_answer(answer: str) -> str:
    """
    Detecta URLs en el texto y agrega www si no existe.
    No bloquea la URL aunque el sitio no responda.
    """
    url_pattern = r"(https?://[^\s]+)"

    def repl(match):
        url = match.group(0)
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path
        if not netloc.startswith("www.") and not netloc.startswith("localhost"):
            netloc = "www." + netloc
        # reconstruir URL, sin verificar con requests
        return urlunparse(parsed._replace(netloc=netloc, path="" if parsed.netloc == "" else parsed.path))

    return re.sub(url_pattern, repl, answer)

def auto_format_code(text: str) -> str:
    text = text.strip()

    if "```" in text:
        return text

    # detectar python
    if not re.search(r"\bdef\s+\w+\(|print\(|return\s+", text):
        return text

    # separar instrucciones en la misma línea
    text = text.replace(";", "\n")

    # arreglar casos como bresultado
    text = re.sub(r"([a-zA-Z0-9_])resultado", r"\1\nresultado", text)

    # saltos después de :
    text = re.sub(r":(?!\n)", ":\n    ", text)

    # return en nueva línea
    text = re.sub(r"\breturn\s+", "\n    return ", text)

    cleaned = textwrap.dedent(text)

    return f"```python\n{cleaned}\n```"


def process_image_links(answer: str) -> str:
    """
    Convierte patrones [IMAGE: URL] en Markdown para que el frontend muestre la imagen.
    """
    pattern = r"\[IMAGE:\s*(https?://[^\]]+)\]"
    
    def repl(match):
        url = match.group(1)
        return f"[![Imagen]({url})]({url})"
    
    return re.sub(pattern, repl, answer)

# ==========================
# ENDPOINT CHAT

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/chat")
async def chat(msg: Message):
    # --- Estado de la conversación ---
    state = conversation_states.get(msg.session_id)
    if not state:
        state = {
            "objective": "Asistir al usuario manteniendo coherencia conversacional",
            "current_topic": "general",
            "history": [],
            "has_introduced": False
        }
        conversation_states[msg.session_id] = state

    if not state.get("current_topic"):
        state["current_topic"] = "general"

    # --- Clasificación de intención ---
    intent = classify_intent(msg.message)
    if intent == "provide_resource":
        state["current_topic"] = "resource"

    # --- Obtener contexto verificado ---
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT question, answer
                    FROM interactions
                    WHERE status = 'stored'
                    ORDER BY id ASC;
                """)
                verified_context = cur.fetchall()

    except Exception as e:
        print("❌ DB ERROR:", e)
        verified_context = []

    # construir contexto igual aunque falle DB
    context_text = ""
    for rec in verified_context:
        context_text += f"P: {rec['question']}\nR: {rec['answer']}\n\n"

    # --- Construir prompt para GPT ---
    system_prompt = f"""
Sos Aimi.
Objetivo: {state['objective']}
Tema actual: {state['current_topic']}

Contexto verificado (respuestas confirmadas):
{context_text}

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

    # --- LOG del prompt ---
    print("\n=== PROMPT QUE SE ENVÍA A GPT ===")
    for m in messages:
        role = m['role']
        content_preview = m['content'][:300]
        print(f"[{role.upper()}]: {content_preview}\n")
    print("=== FIN DEL PROMPT ===\n")

    # --- Llamada a OpenAI ---
    try:
        if not OPENAI_API_KEY:
            raise Exception("Falta OPENAI_API_KEY")

        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages
        )

        answer = completion.choices[0].message.content

    except Exception as e:
        print("❌ OPENAI ERROR:", repr(e))
        answer = "Error generando respuesta"

    # --- Post-procesado ---
    answer = auto_format_code(answer)
    answer = process_image_links(answer)
    answer = process_links_in_answer(answer)

    # --- Actualizar historial ---
    state["history"].append({"role": "user", "content": msg.message})
    state["history"].append({"role": "assistant", "content": answer})
    if len(state["history"]) > MAX_HISTORY:
        state["history"] = state["history"][-MAX_HISTORY:]
    state["has_introduced"] = True

    # --- Guardar en DB ---
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT question, answer
            FROM interactions
            WHERE status = 'stored'
            ORDER BY id ASC;
        """)
        verified_context = cur.fetchall()
    finally:
        if conn:
            conn.close()


    # --- Retornar respuesta ---
    return {
        "answer": answer,
        "source": "ai",
        "prompt_preview": system_prompt
    }

# =========================
# GET INTERACTIONS
# =========================
from fastapi import Query

@app.get("/interactions")
async def get_interactions(
    search: str = Query(None),
    status: str = Query(None),
    limit: int = Query(50),
    offset: int = Query(0)
):

    with get_db() as conn:
        with conn.cursor() as cur:

            query = """
                SELECT id, question, answer, status, topic
                FROM interactions
                WHERE 1=1
            """
            params = []

            if search and search.strip():
                query += " AND (question ILIKE %s OR answer ILIKE %s)"
                params.append(f"%{search}%")
                params.append(f"%{search}%")

            if status:
                query += " AND status = %s"
                params.append(status)

            query += " ORDER BY id DESC LIMIT %s OFFSET %s"
            params.append(limit)
            params.append(offset)

            cur.execute(query, tuple(params))

            return cur.fetchall()

@app.delete("/interactions/{interaction_id}")
async def delete_interaction(interaction_id: int):
    print(f"[DEBUG] DELETE request received for ID: {interaction_id}")

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("[DEBUG] Cursor abierto, ejecutando DELETE...")

            cur.execute("""
                DELETE FROM interactions
                WHERE id = %s
                RETURNING id;
            """, (interaction_id,))
            
            deleted = cur.fetchone()
            print(f"[DEBUG] Resultado DELETE: {deleted}")

            print("[DEBUG] Confirmando cambios en DB...")
            conn.commit()
            print("[DEBUG] Commit realizado")

            if not deleted:
                print("[DEBUG] No se encontró la interacción a eliminar")
                raise HTTPException(status_code=404, detail="Interacción no encontrada")
            
            print(f"[DEBUG] Interacción eliminada: {deleted['id']}")
            return {"status": "deleted", "interaction_id": deleted['id']}
    finally:
        conn.close()
        print("[DEBUG] Conexión cerrada")

class SaveInteraction(BaseModel):
    question: str
    answer: str

@app.post("/interactions/save")
async def save_interaction(data: SaveInteraction):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:

                # 🔍 1. Verificar si ya existe
                cur.execute("""
                    SELECT id FROM interactions
                    WHERE question = %s AND answer = %s
                """, (data.question, data.answer))

                existing = cur.fetchone()

                if existing:
                    return {
                        "ok": True,
                        "msg": "Ya existe",
                        "id": existing["id"]
                    }

                # 💾 2. Insertar si NO existe
                cur.execute("""
                    INSERT INTO interactions (question, answer, status)
                    VALUES (%s, %s, 'pending')
                    RETURNING id;
                """, (data.question, data.answer))

                new_id = cur.fetchone()["id"]
                conn.commit()

        return {"ok": True, "id": new_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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
