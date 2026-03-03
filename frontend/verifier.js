const API = "https://aimi-backend-l2u4.onrender.com";

async function load() {
  const res = await fetch(`${API}/interactions`);
  const data = await res.json();

  const pending = data.filter(i => i.status === "pending");

  document.getElementById("list").innerHTML = pending.map(i => `
    <div class="card">
      <b>P:</b> ${i.question}<br>
      <b>R:</b> ${i.answer}<br><br>
      <button onclick="vote(${i.id}, 5)">⭐⭐⭐⭐⭐ Aprobar</button>
    </div>
  `).join("");
}

async function vote(id, stars) {
  await fetch(`${API}/vote/verifier`, {
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