const chatContainer = document.getElementById("chat");
const input = document.getElementById("userInput");
const button = document.getElementById("sendBtn");
const apiBase = "https://aimi-backend-l2u4.onrender.com";

let sessionId = localStorage.getItem("aimi_session_id");
if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem("aimi_session_id", sessionId);
}

let conversationHistory = [];

// ==========================
function escapeHTML(str) {
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
}

function similarity(a, b) {
    const wa = new Set(a.toLowerCase().split(/\W+/));
    const wb = new Set(b.toLowerCase().split(/\W+/));
    const inter = [...wa].filter(x => wb.has(x)).length;
    return inter / Math.max(wa.size, wb.size);
}

function verificarSiEsNecesario(nuevoMensaje) {
    const THRESHOLD_SIMILARIDAD = 0.7;
    return conversationHistory.some((h, idx) => {
        return h.role === "user" &&
               similarity(nuevoMensaje, h.content) >= THRESHOLD_SIMILIDAD &&
               conversationHistory[idx + 1] &&
               conversationHistory[idx + 1].role === "assistant";
    });
}

// ==========================
// FORMATEAR TEXTO + CÓDIGO
function formatText(text) {

    text = text.replace(/<p>/g, "")
               .replace(/<\/p>/g, "\n")
               .replace(/<strong>/g, "")
               .replace(/<\/strong>/g, "")
               .trim();

    // ======================
    // BLOQUES DE CÓDIGO ````
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang} hljs">${escapeHTML(code.trim())}</code></pre>`;
    });

    // ======================
    // DETECTAR LISTAS
    const lines = text.split("\n");

    let html = "";
    let inUl = false;
    let inOl = false;

    lines.forEach(line => {

        line = line.trim();

        // lista con -
        if (line.match(/^(\-|\*)\s+/)) {

            if (!inUl) {
                html += "<ul>";
                inUl = true;
            }

            html += `<li>${line.replace(/^(\-|\*)\s+/, "")}</li>`;
            return;
        }

        // lista numerada
        if (line.match(/^\d+\.\s+/)) {

            if (!inOl) {
                html += "<ol>";
                inOl = true;
            }

            html += `<li>${line.replace(/^\d+\.\s+/, "")}</li>`;
            return;
        }

        if (inUl) {
            html += "</ul>";
            inUl = false;
        }

        if (inOl) {
            html += "</ol>";
            inOl = false;
        }

        // ======================
        // BLOQUES DESTACADOS

        if (line.startsWith("⚠️")) {
            html += `<div class="aimi-warning">${line}</div>`;
        }
        else if (line.startsWith("🛠")) {
            html += `<div class="aimi-solution">${line}</div>`;
        }
        else if (line.startsWith("💡")) {
            html += `<div class="aimi-tip">${line}</div>`;
        }
        else {
            html += `<p>${line}</p>`;
        }

    });

    if (inUl) html += "</ul>";
    if (inOl) html += "</ol>";

    return html;
}

// ==========================
// COPIAR CÓDIGO
function addCopyButtons() {
    document.querySelectorAll("pre").forEach(pre => {
        if (pre.querySelector(".copy-btn")) return;
        const btn = document.createElement("button");
        btn.innerText = "Copiar";
        btn.className = "copy-btn";
        btn.onclick = () => {
            navigator.clipboard.writeText(pre.innerText);
            btn.innerText = "Copiado!";
            setTimeout(() => btn.innerText = "Copiar", 1500);
        }
        pre.appendChild(btn);
    });
}

function addMessage(text, cls) {
    const div = document.createElement("div");
    div.className = "message " + cls;

    // === Detectar imágenes estilo [IMAGE: URL] ===
    text = text.replace(/\[IMAGE:\s*(https?:\/\/[^\]]+)\]/g, (match, url) =>
        `<a href="${url}" target="_blank">
            <img src="${url}" style="max-width:200px; border-radius:8px; margin:5px 0;">
        </a>`
    );

    // === Formatear el texto primero ===
    let html = formatText(text);

    // === Detectar URLs normales y hacerlas clickeables ===
    html = html.replace(/(https?:\/\/[^\s<\]]+)/g, (url) => {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
    });

    div.innerHTML = html;

    chatContainer.appendChild(div);

    // Resaltar cualquier bloque de código
    div.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));

    addCopyButtons();

    chatContainer.scrollTop = chatContainer.scrollHeight;

    conversationHistory.push({ role: cls === "user" ? "user" : "assistant", content: text });
}

// ==========================
function addThinking() {
    const div = document.createElement("div");
    div.className = "message aimi";
    div.innerHTML = `<div>Aimi está pensando…</div><div class="progress-container"><div class="progress-bar"></div></div>`;
    chatContainer.appendChild(div);
    return div;
}

// ==========================
// AUTO RESIZE TEXTAREA
function autoResizeTextarea() {
    input.style.height = 'auto';
    input.style.height = input.scrollHeight + 'px';
}

// ==========================
// ENVIAR MENSAJE
async function sendMessage() {
    const msg = input.value.trim();
    if (!msg) return;
    addMessage(msg, "user");
    input.value = "";
    autoResizeTextarea();
    const thinking = addThinking();
    try {
        const res = await fetch(`${apiBase}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, message: msg })
        });
        const data = await res.json();
        thinking.remove();
        addMessage(data.answer || "Sin respuesta", "aimi");
    } catch (e) {
        thinking.remove();
        addMessage("Error conectando con servidor", "aimi");
    }
}

// ==========================
// EVENTOS
input.addEventListener("focus", () => {
    setTimeout(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }, 300);
});

input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
input.addEventListener("input", autoResizeTextarea);
button.addEventListener("click", sendMessage);
autoResizeTextarea();