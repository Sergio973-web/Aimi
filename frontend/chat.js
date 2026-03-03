const API = "https://aimi-backend-l2u4.onrender.com/chat";

const chat = document.getElementById("chat");
const input = document.getElementById("userInput");

function add(text, cls) {
  const div = document.createElement("div");
  div.className = "message " + cls;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;

  add(text, "user");
  input.value = "";

  console.log("➡️ Enviando:", text);

  try {
    const res = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    });

    console.log("⬅️ Status:", res.status);

    if (!res.ok) {
      const err = await res.text();
      console.error("❌ Error backend:", err);
      add("Error del servidor", "aimi");
      return;
    }

    const data = await res.json();
    console.log("✅ Respuesta:", data);

    add(data.answer, "aimi");

  } catch (e) {
    console.error("🔥 Error conexión:", e);
    add("No se pudo conectar al servidor", "aimi");
  }
}