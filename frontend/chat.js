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

const micBtn = document.getElementById("micBtn");
const userInput = document.getElementById("userInput");

let recognition;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    
    recognition.lang = 'es-AR'; // español Argentina
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        userInput.value = transcript;

        // Opcional: enviar automáticamente
        // sendMessage(); // descomentar si querés envío automático
    };

    recognition.onerror = (event) => {
        console.error("Error de reconocimiento:", event.error);
    };

} else {
    micBtn.disabled = true;
    micBtn.title = "Tu navegador no soporta reconocimiento de voz";
}

micBtn.addEventListener("click", () => {
    if (recognition) recognition.start();
});

// ==========================
// FORMATEAR TEXTO + CÓDIGO
function formatText(text) {
    text = text.replace(/<p>/g, "").replace(/<\/p>/g, "\n")
               .replace(/<strong>/g, "").replace(/<\/strong>/g, "")
               .trim();

    // Bloques con backticks
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang} hljs">${escapeHTML(code.trim())}</code></pre>`;
    });

    const lines = text.split("\n");
    let html = "";
    let inCodeBlock = false;
    let codeBuffer = [];
    let inUl = false;
    let inOl = false;

    lines.forEach(line => {
        const trimmed = line.trimEnd();

        // Código por indentación
        if (/^( {4}|\t)/.test(line)) {
            codeBuffer.push(line.replace(/^( {4}|\t)/, ""));
            inCodeBlock = true;
            return;
        } 
        if (inCodeBlock) {
            html += `<pre><code class="hljs">${escapeHTML(codeBuffer.join("\n"))}</code></pre>`;
            codeBuffer = [];
            inCodeBlock = false;
        }

        // Lista con -
        if (/^(\-|\*)\s+/.test(trimmed)) {
            if (!inUl) inUl = true, html += "<ul>";
            html += `<li>${trimmed.replace(/^(\-|\*)\s+/, "")}</li>`;
            return;
        }

        // Lista numerada
        if (/^\d+\.\s+/.test(trimmed)) {
            if (!inOl) inOl = true, html += "<ol>";
            html += `<li>${trimmed.replace(/^\d+\.\s+/, "")}</li>`;
            return;
        }

        // Cerrar listas si no corresponde
        if (inUl) { html += "</ul>"; inUl = false; }
        if (inOl) { html += "</ol>"; inOl = false; }

        // Bloques destacados
        if (trimmed.startsWith("⚠️")) html += `<div class="aimi-warning">${trimmed}</div>`;
        else if (trimmed.startsWith("🛠")) html += `<div class="aimi-solution">${trimmed}</div>`;
        else if (trimmed.startsWith("💡")) html += `<div class="aimi-tip">${trimmed}</div>`;
        else html += `<p>${trimmed}</p>`;
    });

    // Cerrar cualquier bloque abierto
    if (inCodeBlock) html += `<pre><code class="hljs">${escapeHTML(codeBuffer.join("\n"))}</code></pre>`;
    if (inUl) html += "</ul>";
    if (inOl) html += "</ol>";

    return html;
}


// ==========================
// COPIAR CÓDIGO
function addCopyButtons() {
    document.querySelectorAll("pre").forEach(pre => {
        if (pre.querySelector(".copy-btn")) return; // evitar duplicados

        const code = pre.querySelector("code");
        if (!code) return; // no hay código, saltear

        const btn = document.createElement("button");
        btn.innerText = "Copiar";
        btn.className = "copy-btn";

        btn.onclick = () => {
            navigator.clipboard.writeText(code.innerText.trim());
            btn.innerText = "Copiado!";
            setTimeout(() => btn.innerText = "Copiar", 1500);
        };

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