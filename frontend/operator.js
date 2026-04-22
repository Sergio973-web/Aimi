const API = "https://aimi-backend-l2u4.onrender.com";

async function load() {
  const res = await fetch(`${API}/interactions`);
  const data = await res.json();

  const ready = data.filter(i => i.status === "expert_approved");

  document.getElementById("list").innerHTML = ready.map(i => `
    <div class="card">
      <b>P:</b> ${i.question}<br>
      <b>R:</b> ${i.answer}<br><br>

      <input id="t${i.id}" placeholder="tema (ej: astrologia_basica)">
      <button onclick="store(${i.id})">🧠 Guardar en memoria</button>
    </div>
  `).join("");
}

async function store(id) {
  const topic = document.getElementById("t" + id).value.trim();
  await fetch(`${API}/operator/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      interaction_id: id,
      topic: topic
    })
  });

  load();
}

load();