document.addEventListener("DOMContentLoaded", () => {
  const status = document.getElementById("console-status");
  if (!status) return;
  const isAdmin = document.getElementById("moderation-script")?.dataset.admin === "true";
  const pendingList = document.getElementById("pending-questions");
  const flagList = document.getElementById("flagged-questions");
  const accessList = document.getElementById("access-requests");
  const accessStatus = document.getElementById("access-status");
  let csrfToken = "";
  let openQuestions = [];
  let domains = [];

  const DECLINE_REASONS = [
    "This has a direct answer that a lookup, definition, or calculator can give. TruthLM is for questions that need an investigation.",
    "Please narrow the question: name the population, setting, or time frame so the evidence can answer it.",
    "A very similar question is already open. Attach to it instead.",
    "This falls outside the domains TruthLM currently covers.",
    "This question is not appropriate for TruthLM.",
  ];

  const api = async (path, options = {}) => {
    const response = await fetch(path, {
      ...options,
      headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken, ...(options.headers || {})}
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(payload.detail) ? payload.detail[0]?.msg : payload.detail;
      throw new Error((detail || `Request failed (${response.status})`).replace(/^Value error, /, ""));
    }
    return payload;
  };

  const el = (tag, props = {}, children = []) => {
    const element = document.createElement(tag);
    Object.entries(props).forEach(([key, value]) => {
      if (key === "text") element.textContent = value;
      else if (key === "className") element.className = value;
      else element.setAttribute(key, value);
    });
    children.forEach((child) => element.appendChild(child));
    return element;
  };
  const option = (value, label, selected = false) => {
    const item = el("option", {value, text: label});
    item.selected = selected;
    return item;
  };
  const labelled = (label, control) => el("label", {}, [document.createTextNode(label), control]);
  const date = (value) => new Date(value).toLocaleDateString();
  const setCount = (id, value) => {
    const badge = document.getElementById(id);
    if (badge) badge.textContent = value ? String(value) : "";
  };
  const empty = (list, message) => list.appendChild(el("p", {className: "review-empty", text: message}));
  const act = async (button, work) => {
    const buttons = button.closest("article")?.querySelectorAll("button") || [button];
    buttons.forEach((item) => { item.disabled = true; });
    try {
      status.textContent = await work();
    } catch (error) {
      status.textContent = error.message;
      buttons.forEach((item) => { item.disabled = false; });
    }
  };

  const loadQueueContext = async () => {
    const payload = await api("/v1/questions");
    openQuestions = payload.questions.filter((item) => item.status === "open");
    domains = payload.domains.filter((item) => item.key !== "unassigned");
    return payload;
  };

  const pendingCard = (item) => {
    const card = el("article", {className: "review-card"});
    card.appendChild(el("p", {className: "review-meta",
      text: `Submitted ${date(item.created_at)}${item.suggested_domain_label ? ` · suggested domain: ${item.suggested_domain_label}` : ""}`}));
    card.appendChild(el("blockquote", {text: item.text}));

    const canonical = el("textarea", {rows: "3", maxlength: "2000"});
    canonical.value = item.normalized_text;
    const domain = el("select", {}, [option("", "Choose a domain")]);
    domains.forEach((group) => domain.appendChild(option(group.key, group.label, group.key === item.suggested_domain)));
    const tags = el("input", {maxlength: "400", placeholder: "optional, comma separated"});
    const attach = el("select", {}, [option("", "No, approve as a new question")]);
    openQuestions.forEach((question) => attach.appendChild(option(question.cluster_id, `${question.domain_label}: ${question.question}`)));
    const approveReason = el("input", {maxlength: "1000"});
    approveReason.value = "Clear, researchable, and within scope.";
    attach.addEventListener("change", () => {
      [canonical, domain, tags].forEach((control) => { control.disabled = Boolean(attach.value); });
    });

    const declinePreset = el("select", {}, DECLINE_REASONS.map((reason, index) => option(String(index), reason)));
    declinePreset.appendChild(option("custom", "Write a different reason"));
    const declineReason = el("textarea", {rows: "3", maxlength: "1000"});
    declineReason.value = DECLINE_REASONS[0];
    declinePreset.addEventListener("change", () => {
      declineReason.value = declinePreset.value === "custom" ? "" : DECLINE_REASONS[Number(declinePreset.value)];
      if (declinePreset.value === "custom") declineReason.focus();
    });

    const approve = el("button", {type: "button", className: "button dark", text: "Approve"});
    approve.addEventListener("click", () => act(approve, async () => {
      const body = {action: "approve", reason: approveReason.value.trim()};
      if (attach.value) body.cluster_id = attach.value;
      else {
        body.canonical_question = canonical.value.trim();
        if (domain.value) body.domain = domain.value;
        body.tags = tags.value.split(",").map((tag) => tag.trim()).filter(Boolean);
      }
      const result = await api(`/v1/admin/submissions/${encodeURIComponent(item.submission_id)}/moderate`,
                               {method: "POST", body: JSON.stringify(body)});
      await loadPending();
      return `Question approved as cluster ${result.cluster_id}. Pass this ID to the Core run.`;
    }));
    const decline = el("button", {type: "button", className: "button reject", text: "Decline with reason"});
    decline.addEventListener("click", () => act(decline, async () => {
      await api(`/v1/admin/submissions/${encodeURIComponent(item.submission_id)}/moderate`,
                {method: "POST", body: JSON.stringify({action: "reject", reason: declineReason.value.trim()})});
      await loadPending();
      return "Question declined. The submitter will see your reason.";
    }));

    card.appendChild(el("div", {className: "review-columns"}, [
      el("div", {className: "review-approve"}, [
        el("h3", {text: "Approve"}),
        labelled("Wording to investigate", canonical),
        labelled("Domain", domain),
        labelled("Tags", tags),
        labelled("Or attach to an open question", attach),
        labelled("Reason (audit trail)", approveReason),
        approve,
      ]),
      el("div", {className: "review-decline"}, [
        el("h3", {text: "Decline"}),
        labelled("Reason", declinePreset),
        labelled("Message to the submitter", declineReason),
        decline,
      ]),
    ]));
    return card;
  };

  const loadPending = async () => {
    await loadQueueContext();
    const payload = await api("/v1/admin/submissions?state=pending");
    pendingList.replaceChildren();
    setCount("pending-count", payload.submissions.length);
    payload.submissions.forEach((item) => pendingList.appendChild(pendingCard(item)));
    if (!payload.submissions.length) empty(pendingList, "No questions are waiting for review.");
  };

  const loadFlags = async () => {
    const payload = await api("/v1/admin/question-reports?status=open");
    flagList.replaceChildren();
    setCount("flag-count", payload.reports.length);
    payload.reports.forEach((report) => {
      const card = el("article", {className: "review-card"});
      card.appendChild(el("p", {className: "review-meta", text: `Flagged ${date(report.created_at)} · ${report.reason}`}));
      card.appendChild(el("blockquote", {text: report.question}));
      if (report.details) card.appendChild(el("p", {text: report.details}));
      const reason = el("input", {maxlength: "1000", placeholder: "What you decided and why"});
      const controls = el("div", {className: "review-actions"});
      [["resolved", "Resolve"], ["dismissed", "Dismiss"]].forEach(([value, label]) => {
        const button = el("button", {type: "button", className: value === "resolved" ? "button dark" : "button quiet", text: label});
        button.addEventListener("click", () => act(button, async () => {
          await api(`/v1/admin/question-reports/${encodeURIComponent(report.report_id)}/resolve`,
                    {method: "POST", body: JSON.stringify({status: value, reason: reason.value.trim()})});
          await loadFlags();
          return `Flag ${value}.`;
        }));
        controls.appendChild(button);
      });
      card.append(labelled("Decision reason", reason), controls);
      flagList.appendChild(card);
    });
    if (!payload.reports.length) empty(flagList, "No open flags.");
  };

  const ACCESS_ACTIONS = {
    pending: [["approve", "Approve", "Subscription opened."], ["decline", "Decline", "Not in the current batch."]],
    declined: [["approve", "Approve", "Subscription opened."]],
    revoked: [["approve", "Restore access", "Access restored."]],
    approved: [["revoke", "Revoke access", "Access revoked."]],
  };
  const loadAccess = async () => {
    const payload = await api(`/v1/admin/access-requests?status=${encodeURIComponent(accessStatus.value)}`);
    accessList.replaceChildren();
    if (accessStatus.value === "pending") setCount("access-count", payload.requests.length);
    payload.requests.forEach((item) => {
      const card = el("article", {className: "review-card access-card"});
      const who = [item.role, item.discipline].filter(Boolean).join(" · ");
      card.appendChild(el("p", {className: "review-meta", text: `${item.status} · ${item.source} · ${date(item.created_at)}`}));
      card.appendChild(el("h3", {text: item.name || item.email}));
      card.appendChild(el("p", {className: "access-email", text: item.email}));
      if (who) card.appendChild(el("p", {text: who}));
      if (item.note) card.appendChild(el("blockquote", {text: item.note}));
      if (item.decision_reason) card.appendChild(el("p", {className: "review-meta", text: `Last decision: ${item.decision_reason}`}));
      const actions = ACCESS_ACTIONS[item.status] || [];
      if (actions.length) {
        const reason = el("input", {maxlength: "1000"});
        reason.value = actions[0][2];
        const controls = el("div", {className: "review-actions"});
        actions.forEach(([action, label, defaultReason]) => {
          const button = el("button", {type: "button", className: action === "approve" ? "button dark" : "button reject", text: label});
          button.addEventListener("focus", () => { if (!reason.dataset.edited) reason.value = defaultReason; });
          button.addEventListener("click", () => act(button, async () => {
            const result = await api(`/v1/admin/access-requests/${encodeURIComponent(item.request_id)}/decision`,
                                     {method: "POST", body: JSON.stringify({action, reason: reason.value.trim()})});
            await loadAccess();
            if (action !== "approve") return `Access ${result.status}.`;
            return result.notified ? "Approved. The subscription is active and a welcome email is on its way." : "Approved and subscribed, but the welcome email could not be sent. Let them know directly.";
          }));
          controls.appendChild(button);
        });
        reason.addEventListener("input", () => { reason.dataset.edited = "true"; });
        card.append(labelled("Reason (audit trail)", reason), controls);
      }
      accessList.appendChild(card);
    });
    if (!payload.requests.length) empty(accessList, "Nothing to show here.");
  };

  document.getElementById("invite-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const result = await api("/v1/admin/access", {method: "POST", body: JSON.stringify({
        email: document.getElementById("invite-email").value.trim(),
        name: document.getElementById("invite-name").value.trim(),
        reason: document.getElementById("invite-reason").value.trim()})});
      form.reset();
      document.getElementById("invite-reason").value = "Invited to subscribe.";
      status.textContent = result.idempotent_replay ? `${result.email} is already a subscriber.`
        : result.notified ? `${result.email} is subscribed and has been emailed.` : `${result.email} is subscribed, but the welcome email could not be sent.`;
      await loadAccess();
    } catch (error) {
      status.textContent = error.message;
    } finally { button.disabled = false; }
  });
  accessStatus?.addEventListener("change", () => loadAccess().catch((error) => { status.textContent = error.message; }));

  fetch("/v1/auth/session").then((response) => response.json()).then(async (identity) => {
    csrfToken = identity.csrf_token || "";
    await Promise.all([loadPending(), loadFlags(), ...(isAdmin ? [loadAccess()] : [])]);
    status.textContent = "Review queue is up to date.";
  }).catch((error) => {
    status.textContent = `Unable to load the review console: ${error.message}`;
  });
});
