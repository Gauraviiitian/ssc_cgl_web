// Visual-only timer on the question page; the server measures actual elapsed
// time from when it served the question, so this never affects scoring.
(function () {
  const timerEl = document.getElementById("timer");
  if (!timerEl) return;
  let seconds = 0;
  setInterval(function () {
    seconds += 1;
    timerEl.textContent = seconds + "s";
  }, 1000);
})();

async function loadExplanation(sessionId, questionId) {
  const box = document.getElementById("explanation-box");
  box.innerHTML = "<p class='muted'>Loading explanation…</p>";
  const res = await fetch(`/mock/${sessionId}/explain/${questionId}`);
  const html = await res.text();
  box.innerHTML = html;
}
