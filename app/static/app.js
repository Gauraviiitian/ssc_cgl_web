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

// Dashboard tab switcher (Mock Test / Current Affairs / My Performance / Paid Mock Tests).
// Also honors a #<tab-name> URL hash on load, so redirects (e.g. after
// /paid/unlock) can land the user on the right tab.
(function () {
  const tabs = document.querySelectorAll(".tab");
  if (!tabs.length) return;

  function activate(tab) {
    tabs.forEach(function (t) {
      t.classList.remove("active");
      t.setAttribute("aria-selected", "false");
    });
    tab.classList.add("active");
    tab.setAttribute("aria-selected", "true");
    document.querySelectorAll(".tab-panel").forEach(function (p) {
      p.hidden = true;
    });
    document.getElementById("panel-" + tab.dataset.tab).hidden = false;
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      activate(tab);
    });
  });

  const hash = location.hash.replace("#", "");
  const targetTab = hash && document.querySelector('.tab[data-tab="' + hash + '"]');
  if (targetTab) activate(targetTab);
})();

async function loadExplanation(sessionId, questionId) {
  const box = document.getElementById("explanation-box");
  box.innerHTML = "<p class='muted'>Loading explanation…</p>";
  const res = await fetch(`/mock/${sessionId}/explain/${questionId}`);
  const html = await res.text();
  box.innerHTML = html;
}
