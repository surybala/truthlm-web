document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("question-form");
  if (!form) return;
  const question = document.getElementById("question-text");
  const domain = document.getElementById("question-domain");
  const status = document.getElementById("question-form-status");
  const history = document.getElementById("submission-history");
  const search = document.getElementById("question-search");
  const count = document.getElementById("queue-count");
  let csrfToken = null;
  let submissions = [];

  const api = async (path, options = {}) => {
    const response = await fetch(path, {...options, headers: {
      "Content-Type": "application/json", ...(csrfToken ? {"X-CSRF-Token": csrfToken} : {}),
      ...(options.headers || {})
    }});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    return payload;
  };

  const addText = (parent, tag, value, className = "") => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    parent.appendChild(node);
    return node;
  };

  const render = () => {
    const term = search.value.trim().toLowerCase();
    const visible = submissions.filter((item) =>
      !term || `${item.text} ${item.answer || ""}`.toLowerCase().includes(term));
    history.replaceChildren();
    count.textContent = `${visible.length} ${visible.length === 1 ? "question" : "questions"}`;
    visible.forEach((item) => {
      const card = document.createElement("article");
      card.className = "private-answer-card";
      const meta = document.createElement("div");
      meta.className = "private-answer-meta";
      addText(meta, "span", item.answer ? "Answered" : "In research", `moderation ${item.answer ? "approved" : "pending"}`);
      addText(meta, "time", new Date(item.created_at).toLocaleDateString());
      card.appendChild(meta);
      addText(card, "h3", item.text);
      if (item.answer) {
        const answer = document.createElement("div");
        answer.className = "private-answer-copy";
        addText(answer, "p", "Research answer", "eyebrow");
        addText(answer, "p", item.answer);
        card.appendChild(answer);
      } else {
        addText(card, "p", "Our research team is working on this question. The answer will appear here when it is ready.", "history-reason");
      }
      history.appendChild(card);
    });
    if (!visible.length) {
      addText(history, "h3", term ? "No research matches your search." : "No private questions yet.");
      addText(history, "p", term ? "Try a broader phrase." : "Submit your first question to begin your research library.", "loading-line");
    }
  };

  const loadHistory = async () => {
    submissions = (await api("/v1/me/submissions")).submissions;
    render();
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    button.disabled = true;
    try {
      const body = {text: question.value};
      if (domain.value) body.domain = domain.value;
      await api("/v1/questions", {method: "POST", headers: {"Idempotency-Key": crypto.randomUUID()}, body: JSON.stringify(body)});
      form.reset();
      status.textContent = "Your private question has been submitted for research.";
      await loadHistory();
    } catch (error) {
      status.textContent = error.message;
    } finally { button.disabled = false; }
  });
  search.addEventListener("input", render);
  fetch("/v1/auth/session").then((response) => response.json()).then(async (identity) => {
    csrfToken = identity.csrf_token || null;
    await loadHistory();
  }).catch((error) => { history.textContent = `Unable to load your research: ${error.message}`; });
});
