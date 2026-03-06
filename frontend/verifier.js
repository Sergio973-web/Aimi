const apiBase = "https://aimi-backend-l2u4.onrender.com";
const container = document.getElementById("interactions");



// Cargar interacciones
async function loadInteractions() {
    const res = await fetch(`${apiBase}/interactions`);
    const data = await res.json();
    const container = document.getElementById("interactions");
    container.innerHTML = "";

    data.forEach(interaction => {
        if(interaction.status === "pending") {
            const div = document.createElement("div");
            div.classList.add("interaction");
            div.dataset.id = interaction.id;

            div.innerHTML = `
                <div class="question">P: ${interaction.question}</div>
                <div class="answer">R: ${formatTextVerificador(interaction.answer)}</div>
                <div class="stars">
                    <button data-stars="1">⭐ 1</button>
                    <button data-stars="2">⭐⭐ 2</button>
                    <button data-stars="3">⭐⭐⭐ 3</button>
                </div>
                <div class="feedback"></div>
            `;
            container.appendChild(div);

            // Resaltar código
            div.querySelectorAll('pre code').forEach(block=>{
                hljs.highlightElement(block);
            });

            // Botones de estrellas
            div.querySelectorAll(".stars button").forEach(btn => {
                btn.addEventListener("click", async () => {
                    const stars = parseInt(btn.dataset.stars);
                    const id = interaction.id;
                    const feedback = div.querySelector(".feedback");

                    await fetch(`${apiBase}/vote/verifier`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ interaction_id: id, stars })
                    });

                    if(stars === 1){
                        feedback.textContent = "❌ Eliminado del verificador";
                        div.remove();
                    } else if(stars === 2){
                        feedback.textContent = "🔹 Se queda en verificador";
                        feedback.classList.add("show");
                        setTimeout(()=>feedback.classList.remove("show"),2000);
                    } else if(stars === 3){
                        feedback.textContent = "✅ Pasó al experto";
                        div.remove();
                    }
                });
            });
        }
    });

    // Agregar botones de copiar
    addCopyButtons();
}


// Escapar HTML
function escapeHTML(str) {
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// Formatear texto y código como en index
function formatTextVerificador(text) {
    text = text.replace(/<p>/g, "")
               .replace(/<\/p>/g, "\n")
               .replace(/<strong>/g, "")
               .replace(/<\/strong>/g, "")
               .trim();

    if (text.startsWith("```")) {
        const match = text.match(/```(\w*)\n([\s\S]*?)```/);
        if (match) {
            const lang = match[1] || "";
            const code = match[2].trim();
            return `<pre><code class="language-${lang} hljs">${escapeHTML(code)}</code></pre>`;
        }
    }

    const simpleCodePatterns = ["def ", "class ", "print(", "return ", "console.log", "function "];
    if (simpleCodePatterns.some(p => text.includes(p))) {
        let lang = text.includes("def ") || text.includes("class ") ? "python" : "javascript";
        let content = text.replace(/;/g, ";\n").replace(/:/g, ":\n").trim();
        return `<pre><code class="language-${lang} hljs">${escapeHTML(content)}</code></pre>`;
    }

    const lines = text.split("\n");
    let html = "";
    lines.forEach(line => {
        line = line.trim();
        html += `<p>${line}</p>`;
    });
    return html;
}


// Agregar botón de copiar a cada bloque
function addCopyButtons() {
    document.querySelectorAll("pre").forEach(pre=>{
        if(pre.querySelector(".copy-btn")) return;
        const btn = document.createElement("button");
        btn.innerText = "Copiar";
        btn.className = "copy-btn";
        btn.onclick = () => {
            const code = pre.innerText;
            navigator.clipboard.writeText(code);
            btn.innerText = "Copiado!";
            setTimeout(()=>btn.innerText="Copiar",1500);
        }
        pre.appendChild(btn);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    loadInteractions();
    setInterval(loadInteractions, 90000);
});