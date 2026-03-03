const apiBase = "https://aimi-backend-l2u4.onrender.com";
const container = document.getElementById("interactions");

async function loadInteractions() {
    const res = await fetch(`${apiBase}/interactions`);
    const data = await res.json();
    container.innerHTML = ""; // limpiar

    data.forEach(interaction => {
        if(interaction.status !== "stored" && interaction.status !== "expert_approved") {
            const div = document.createElement("div");
            div.classList.add("interaction-card");
            div.dataset.id = interaction.id;

            div.innerHTML = `
                <div class="question"><strong>P:</strong> ${interaction.question}</div>
                <div class="answer"><strong>R:</strong> ${interaction.answer}</div>
                <div class="stars">
                    <button data-stars="1">⭐ 1</button>
                    <button data-stars="2">⭐⭐ 2</button>
                    <button data-stars="3">⭐⭐⭐ 3</button>
                </div>
            `;

            container.appendChild(div);

            // agregar listener a los botones de estrellas
            div.querySelectorAll(".stars button").forEach(btn => {
                btn.addEventListener("click", async () => {
                    const stars = parseInt(btn.dataset.stars);
                    const id = interaction.id;

                    if(stars === 1) {
                        await fetch(`${apiBase}/vote/verifier`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ interaction_id: id, stars })
                        });
                        div.remove(); // eliminar del DOM
                    } else if(stars === 2) {
                        await fetch(`${apiBase}/vote/verifier`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ interaction_id: id, stars })
                        });
                        // queda en verificador, opcional animación
                        div.classList.add("highlight");
                        setTimeout(() => div.classList.remove("highlight"), 1000);
                    } else if(stars === 3) {
                        await fetch(`${apiBase}/vote/expert`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ interaction_id: id, stars })
                        });
                        div.remove(); // eliminar del verificador porque pasó a experto
                    }
                });
            });
        }
    });
}

// cargar inicialmente
loadInteractions();