const apiBase = "https://aimi-backend-l2u4.onrender.com";

async function loadInteractions() {
    const res = await fetch(`${apiBase}/interactions`);
    const data = await res.json();
    const container = document.getElementById("interactions");
    container.innerHTML = "";

    data.forEach(interaction => {
        if(interaction.status !== "stored") {
            const div = document.createElement("div");
            div.classList.add("interaction");

            div.innerHTML = `
                <div class="question">P: ${interaction.question}</div>
                <div class="answer">R: ${interaction.answer}</div>
                <div class="stars">
                    <button onclick="vote(${interaction.id}, 1)">⭐ 1</button>
                    <button onclick="vote(${interaction.id}, 2)">⭐⭐ 2</button>
                    <button onclick="vote(${interaction.id}, 3)">⭐⭐⭐ 3</button>
                </div>
            `;
            container.appendChild(div);
        }
    });
}

async function vote(interaction_id, stars) {
    if (stars === 1) {
        // ⭐ 1: eliminar del verificador
        await fetch(`${apiBase}/vote/verifier`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ interaction_id, stars })
        });
        alert("Eliminado del verificador");
    } else if (stars === 2) {
        // ⭐ 2: dejar en verificador
        await fetch(`${apiBase}/vote/verifier`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ interaction_id, stars })
        });
        alert("Se queda en verificador");
    } else if (stars === 3) {
        // ⭐ 3: pasar a experto
        await fetch(`${apiBase}/vote/expert`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ interaction_id, stars })
        });
        alert("Pasó al experto");
    }

    loadInteractions(); // recarga la lista
}

// Carga inicial
loadInteractions();