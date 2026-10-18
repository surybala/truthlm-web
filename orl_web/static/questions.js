document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("question-form");
  if (!form) return;
  const question = document.getElementById("question-text");
  const domain = document.getElementById("question-domain");
  const status = document.getElementById("question-form-status");
  const approved = document.getElementById("approved-questions");
  const approvedCount = document.getElementById("approved-count");
  const history = document.getElementById("submission-history");
  let csrfToken = null;

  const api = async (path, options = {}) => {
    const response = await fetch(path, {...options, headers: {
      "Content-Type": "application/json", ...(csrfToken ? {"X-CSRF-Token": csrfToken} : {}),
      ...(options.headers || {})
    }});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(payload.detail) ? payload.detail[0]?.msg : payload.detail;
      throw new Error((detail || `Request failed (${response.status})`).replace(/^Value error, /, ""));
    }
    return payload;
  };

  const addText = (parent, tag, value, className = "") => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    parent.appendChild(node);
    return node;
  };

  const loadApproved = async () => {
    const payload = await api("/v1/questions");
    approved.replaceChildren();
    approvedCount.textContent = `${payload.questions.length} ${payload.questions.length === 1 ? "question" : "questions"}`;
    payload.domains.forEach((group) => {
      const items = payload.questions.filter((item) => item.domain === group.key);
      if (!items.length) return;
      addText(approved, "h3", group.label, "workspace-domain");
      items.forEach((item) => {
        const card = document.createElement("article");
        card.className = "workspace-item";
        const meta = document.createElement("div");
        meta.className = "workspace-meta";
        addText(meta, "span", item.status, `moderation ${item.status === "open" ? "approved" : "pending"}`);
        addText(meta, "span", item.readiness ? `readiness: ${item.readiness.label}` : "readiness not assessed");
        card.appendChild(meta);
        addText(card, "h4", item.question);
        addText(card, "p", `Cluster ID: ${item.cluster_id}`, "workspace-id");
        approved.appendChild(card);
      });
    });
    if (!payload.questions.length) addText(approved, "p", "No approved questions yet.", "loading-line");
  };

  const loadHistory = async () => {
    const payload = await api("/v1/me/submissions");
    history.replaceChildren();
    payload.submissions.forEach((item) => {
      const card = document.createElement("article");
      card.className = "workspace-item";
      const meta = document.createElement("div");
      meta.className = "workspace-meta";
      addText(meta, "span", item.moderation_state, `moderation ${item.moderation_state}`);
      addText(meta, "time", new Date(item.created_at).toLocaleDateString());
      card.appendChild(meta);
      addText(card, "h4", item.text);
      if (item.cluster_id) addText(card, "p", `Cluster ID: ${item.cluster_id}`, "workspace-id");
      if (item.moderation_reason) addText(card, "p", item.moderation_reason, "history-reason");
      history.appendChild(card);
    });
    if (!payload.submissions.length) addText(history, "p", "You have not submitted a question yet.", "loading-line");
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
      status.textContent = "Submitted. Approve it in the review console to get its cluster ID.";
      await loadHistory();
    } catch (error) {
      status.textContent = error.message;
    } finally { button.disabled = false; }
  });

  fetch("/v1/auth/session").then((response) => response.json()).then(async (identity) => {
    csrfToken = identity.csrf_token || null;
    await Promise.all([loadApproved(), loadHistory()]);
  }).catch((error) => { history.textContent = `Unable to load questions: ${error.message}`; });
});
