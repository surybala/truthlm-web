document.addEventListener("DOMContentLoaded", () => {
  const results = document.getElementById("question-results");
  if (!results) return;
  const search = document.getElementById("question-search");
  const domainFilter = document.getElementById("domain-filter");
  const readinessFilter = document.getElementById("readiness-filter");
  const count = document.getElementById("queue-count");
  const cycleLabel = document.getElementById("cycle-label");
  const questionForm = document.getElementById("question-form");
  const questionText = document.getElementById("question-text");
  const questionDomain = document.getElementById("question-domain");
  const questionStatus = document.getElementById("question-form-status");
  const similar = document.getElementById("similar-questions");
  const history = document.getElementById("submission-history");
  const reportDialog = document.getElementById("report-dialog");
  const reportForm = document.getElementById("report-form");
  let reportCluster = null;
  let questions = [];
  let domains = [];
  let votingOpen = false;
  let csrfToken = null;

  const api = async (path, options = {}) => {
    const response = await fetch(path, {
      ...options,
      headers: {"Content-Type": "application/json", ...(csrfToken ? {"X-CSRF-Token": csrfToken} : {}),
                ...(options.headers || {})}
    });
    const payload = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(payload.detail) ? payload.detail[0]?.msg : payload.detail;
      throw new Error((detail || `Request failed (${response.status})`).replace(/^Value error, /, ""));
    }
    return payload;
  };

  const addText = (parent, tag, value, className = "") => {
    const element = document.createElement(tag);
    element.textContent = value;
    if (className) element.className = className;
    parent.appendChild(element);
    return element;
  };

  const readiness = (item) => {
    if (!item) return {key: "unassessed", label: "Readiness not yet assessed"};
    const key = item.label.toLowerCase();
    const labels = {high: "Strong research backing", medium: "Developing research backing", low: "Limited research backing"};
    return {key, label: labels[key] || item.label};
  };

  const questionRow = (item, position) => {
    const row = document.createElement("article");
    row.className = "queue-question";
    addText(row, "span", position ? String(position) : "", "queue-rank");
    const body = document.createElement("div");
    body.className = "queue-question-body";
    const meta = document.createElement("div");
    meta.className = "question-meta";
    if (item.status === "selected") addText(meta, "span", "Selected for investigation", "selected-badge");
    const ready = readiness(item.readiness);
    addText(meta, "span", ready.label, `readiness ${ready.key}`);
    item.tags.forEach((tag) => addText(meta, "span", tag, "topic-tag"));
    body.appendChild(meta);
    addText(body, "h3", item.question);
    if (item.readiness?.reasons?.length) {
      addText(body, "p", item.readiness.reasons[0].summary || "Assessment details are available.", "readiness-reason");
    }
    const flag = addText(body, "button", "Flag for review", "report-link");
    flag.type = "button";
    flag.addEventListener("click", () => {
      reportCluster = item.cluster_id;
      document.getElementById("report-status").textContent = "";
      reportDialog.showModal();
    });
    const voteArea = document.createElement("div");
    voteArea.className = "queue-vote";
    const canVote = votingOpen && item.status === "open";
    const vote = addText(voteArea, "button", item.viewer_has_voted ? "Upvoted" : "Upvote",
                         item.viewer_has_voted ? "vote-button active" : "vote-button");
    vote.type = "button";
    vote.setAttribute("aria-pressed", String(item.viewer_has_voted));
    vote.disabled = !canVote;
    vote.title = canVote ? "Toggle your upvote" : "Upvoting opens with the next weekly cycle";
    addText(voteArea, "span", `${item.votes} upvote${item.votes === 1 ? "" : "s"}`);
    vote.addEventListener("click", async () => {
      vote.disabled = true;
      try {
        await api(`/v1/questions/${encodeURIComponent(item.cluster_id)}/vote`, {
          method: item.viewer_has_voted ? "DELETE" : "PUT"
        });
        item.viewer_has_voted = !item.viewer_has_voted;
        item.votes += item.viewer_has_voted ? 1 : -1;
        render();
      } catch (error) {
        vote.disabled = false;
        vote.title = error.message;
      }
    });
    row.append(body, voteArea);
    return row;
  };

  const render = () => {
    const term = search.value.trim().toLowerCase();
    const domain = domainFilter.value;
    const level = readinessFilter.value;
    const visible = questions.filter((item) => {
      const haystack = `${item.question} ${item.tags.join(" ")} ${item.domain_label}`.toLowerCase();
      return (!term || haystack.includes(term)) && (domain === "all" || item.domain === domain) &&
        (level === "all" || readiness(item.readiness).key === level);
    });
    results.replaceChildren();
    count.textContent = `${visible.length} question${visible.length === 1 ? "" : "s"}`;
    domains.forEach((group) => {
      const byServerOrder = (item) => questions.indexOf(item);
      const open = visible.filter((item) => item.domain === group.key && item.status === "open")
        .sort((a, b) => b.votes - a.votes || byServerOrder(a) - byServerOrder(b));
      const selected = visible.filter((item) => item.domain === group.key && item.status !== "open");
      const items = open.concat(selected);
      if (!items.length) return;
      const section = document.createElement("section");
      section.className = "domain-group";
      const heading = document.createElement("div");
      heading.className = "domain-heading";
      addText(heading, "h2", group.label);
      addText(heading, "span", `${open.length} open question${open.length === 1 ? "" : "s"} · ranked by upvotes`);
      section.appendChild(heading);
      items.forEach((item, index) => section.appendChild(questionRow(item, item.status === "open" ? index + 1 : null)));
      results.appendChild(section);
    });
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "queue-empty";
      const filtered = Boolean(term) || domain !== "all" || level !== "all";
      addText(empty, "h2", filtered ? "No questions match these filters." : "No approved questions yet.");
      addText(empty, "p", filtered ? "Try a broader search, another domain, or all readiness levels." : "Questions appear here after a reviewer approves them. Yours could be the first.");
      results.appendChild(empty);
    }
  };

  const loadQuestions = async () => {
    const payload = await api("/v1/questions");
    questions = payload.questions;
    domains = payload.domains;
    const selected = domainFilter.value;
    domainFilter.replaceChildren();
    addText(domainFilter, "option", "All domains").value = "all";
    domains.forEach((group) => { addText(domainFilter, "option", group.label).value = group.key; });
    domainFilter.value = domains.some((group) => group.key === selected) ? selected : "all";
    votingOpen = Boolean(payload.cycle) && new Date(payload.cycle.ends_at) > new Date();
    cycleLabel.textContent = payload.cycle
      ? `Week ${payload.cycle.key} · upvoting closes ${new Date(payload.cycle.ends_at).toLocaleDateString()}`
      : "Upvoting reopens with the next weekly cycle";
    render();
  };

  const decisionLabels = {pending: "Awaiting review", approved: "Approved", rejected: "Declined"};
  const loadHistory = async () => {
    const payload = await api("/v1/me/submissions");
    history.replaceChildren();
    payload.submissions.forEach((item) => {
      const row = document.createElement("div");
      row.className = "history-row";
      addText(row, "span", decisionLabels[item.moderation_state] || item.moderation_state, `moderation ${item.moderation_state}`);
      addText(row, "small", new Date(item.created_at).toLocaleDateString());
      addText(row, "p", item.text);
      if (item.moderation_reason) addText(row, "p", `Reviewer note: ${item.moderation_reason}`, "history-reason");
      history.appendChild(row);
    });
    if (!payload.submissions.length) addText(history, "p", "You have not asked a question yet.", "loading-line");
  };

  const words = (value) => new Set(value.toLowerCase().match(/[a-z0-9]{3,}/g) || []);
  const similarity = (left, right) => {
    const a = words(left); const b = words(right);
    if (!a.size || !b.size) return 0;
    const overlap = [...a].filter((word) => b.has(word)).length;
    return overlap / (a.size + b.size - overlap);
  };
  questionText.addEventListener("input", () => {
    const matches = questions.map((item) => ({item, score: similarity(questionText.value, item.question)}))
      .filter((match) => match.score >= 0.24).sort((a, b) => b.score - a.score).slice(0, 3);
    similar.replaceChildren();
    similar.hidden = !matches.length;
    if (matches.length) {
      addText(similar, "strong", "A similar question may already be open. Consider upvoting it instead.");
      matches.forEach(({item}) => {
        const button = addText(similar, "button", item.question);
        button.type = "button";
        button.addEventListener("click", () => {
          search.value = item.question;
          domainFilter.value = "all";
          render();
          document.querySelector(".queue-main").scrollIntoView({behavior: "smooth"});
        });
      });
    }
  });

  questionForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = questionForm.querySelector("button[type='submit']");
    button.disabled = true;
    try {
      const body = {text: questionText.value};
      if (questionDomain.value) body.domain = questionDomain.value;
      await api("/v1/questions", {method: "POST", headers: {"Idempotency-Key": crypto.randomUUID()},
                                  body: JSON.stringify(body)});
      questionText.value = "";
      questionDomain.value = "";
      similar.hidden = true;
      questionStatus.textContent = "Sent for review. You will see the decision under Your questions.";
      await loadHistory();
    } catch (error) {
      questionStatus.textContent = error.message;
    } finally { button.disabled = false; }
  });

  search.addEventListener("input", render);
  domainFilter.addEventListener("change", render);
  readinessFilter.addEventListener("change", render);
  document.querySelector(".report-cancel")?.addEventListener("click", () => reportDialog.close());
  reportForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("report-status");
    try {
      await api(`/v1/questions/${encodeURIComponent(reportCluster)}/report`, {method: "POST",
        body: JSON.stringify({reason: document.getElementById("report-reason").value,
                              details: document.getElementById("report-details").value})});
      status.textContent = "Flag received. Thank you.";
      setTimeout(() => reportDialog.close(), 700);
    } catch (error) { status.textContent = error.message; }
  });

  fetch("/v1/auth/session").then((response) => response.json()).then(async (identity) => {
    csrfToken = identity.csrf_token || null;
    await loadQuestions();
    await loadHistory();
  }).catch((error) => {
    results.textContent = `Unable to load questions: ${error.message}`;
  });
});
