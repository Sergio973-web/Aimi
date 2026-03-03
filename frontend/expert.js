const API = "https://aimi-backend-l2u4.onrender.com";

async function load() {
  const res = await fetch(`${API}/interactions`);
  const data = await res.json();

  const verified = data.filter(i => i.status === "verified");

  document.getElementById("list").innerHTML = verified.map(i => `
    <div class="card">
      <b>P:</b> ${i.question}<br>
      <b>R:</b> ${i.answer}<br><br>
      <button onclick="vote(${i.id}, 5)">✅ Aprobar como Experto</button>
    </div>
  `).join("");
}

async function vote(id, stars) {
  await fetch(`${API}/vote/expert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      interaction_id: id,
      stars: stars
    })
  });
  load();
}

load();