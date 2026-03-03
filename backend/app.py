from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, json, math
from dotenv import load_dotenv
from openai import OpenAI

# ==========================
# Configuración
# ==========================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY no está configurada")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="Aimi Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# Persistencia (Render)
# ==========================
DATA_DIR = "data"
MEMORY_DIR = os.path.join(DATA_DIR, "memory")
INTERACTIONS_FILE = os.path.join(DATA_DIR, "interactions.json")

os.makedirs(MEMORY_DIR, exist_ok=True)

# ==========================
# Helpers
# ==========================
def load_interactions():
    if os.path.exists(INTERACTIONS_FILE):
        with open(INTERACTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_interactions(data):
    with open(INTERACTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

interactions = load_interactions()

# ==========================
# Modelos
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
# Embeddings
# ==========================
def embedding(text: str):
    return client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    ).data[0].embedding

def cosine(a, b):
    return sum(x*y for x, y in zip(a, b)) / (
        math.sqrt(sum(x*x for x in a)) *
        math.sqrt(sum(y*y for y in b))
    )

def search_memory(question: str):
    q_emb = embedding(question)
    best = None
    best_score = 0.80

    for file in os.listdir(MEMORY_DIR):
        path = os.path.join(MEMORY_DIR, file)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                score = cosine(q_emb, item["embedding"])
                if score > best_score:
                    best = item
                    best_score = score
    return best

# ==========================
# Endpoints
# ==========================
@app.get("/")
def root():
    return {"status": "Aimi backend online"}

@app.post("/chat")
def chat(msg: Message):
    memory = search_memory(msg.message)
    context = f"Contexto previo: {memory['answer']}" if memory else ""

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu nombre es Aimi. "
                        "Siempre debés presentarte como Aimi. "
                        "Sos una asistente inteligente en aprendizaje. "
                        "Nunca digas que sos ChatGPT ni menciones OpenAI."
                    )
                },
                {"role": "user", "content": context + "\n\n" + msg.message}
            ]
        )
        answer = completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    interaction = {
        "id": len(interactions) + 1,
        "question": msg.message,
        "answer": answer,
        "verifier_votes": [],
        "expert_votes": [],
        "status": "pending"
    }

    interactions.append(interaction)
    save_interactions(interactions)

    return interaction

@app.get("/interactions")
def get_interactions():
    return interactions

@app.post("/vote/verifier")
def vote_verifier(v: Vote):
    i = next((x for x in interactions if x["id"] == v.interaction_id), None)
    if not i:
        raise HTTPException(status_code=404, detail="Interaction not found")

    i["verifier_votes"].append(v.stars)
    if all(s == 5 for s in i["verifier_votes"]):
        i["status"] = "verified"

    save_interactions(interactions)
    return {"ok": True}

@app.post("/vote/expert")
def vote_expert(v: Vote):
    i = next((x for x in interactions if x["id"] == v.interaction_id), None)
    if not i:
        raise HTTPException(status_code=404, detail="Interaction not found")

    i["expert_votes"].append(v.stars)
    if all(s == 5 for s in i["expert_votes"]):
        i["status"] = "expert_approved"

    save_interactions(interactions)
    return {"ok": True}

@app.post("/operator/approve")
def approve(a: Approve):
    i = next((x for x in interactions if x["id"] == a.interaction_id), None)
    if not i:
        raise HTTPException(status_code=404, detail="Interaction not found")

    emb = embedding(i["question"] + " " + i["answer"])
    path = os.path.join(MEMORY_DIR, f"{a.topic}.json")

    data = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

    data.append({
        "question": i["question"],
        "answer": i["answer"],
        "embedding": emb
    })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    i["status"] = "stored"
    save_interactions(interactions)

    return {"stored": True}