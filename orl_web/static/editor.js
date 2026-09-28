document.addEventListener("DOMContentLoaded", () => {
  const status = document.getElementById("editor-status");
  if (!status) return;
  const workspace = document.getElementById("editor-workspace");
  const queue = document.getElementById("editor-queue");
  const detail = document.getElementById("editor-detail");
  let csrfToken = "";

  const api = async (path, options = {}) => {
    const response = await fetch(path, {
      ...options,
      headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken,
                ...(options.headers || {})}
    });
    const payload = await response.json().catch(() => ({detail: "Invalid server response"}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    return payload;
  };

  const addText = (parent, tag, value, className = "") => {
    const element = document.createElement(tag);
    element.textContent = value;
    if (className) element.className = className;
    parent.appendChild(element);
    return element;
  };

  const loadDetail = async (bundleId) => {
    const item = await api(`/v1/admin/publications/${encodeURIComponent(bundleId)}`);
    detail.replaceChildren();
    addText(detail, "p", `Revision ${item.revision} · ${item.status}`, "editor-kicker");
    addText(detail, "h2", item.title);
    addText(detail, "p", item.summary, "editor-summary");
    if (item.correction_summary) addText(detail, "p", `Correction: ${item.correction_summary}`, "editor-correction");

    const gateHeading = addText(detail, "h3", "Publication gates");
    gateHeading.id = "editor-gates";
    const gates = document.createElement("div");
    gates.className = "editor-gates";
    item.gates.forEach((gate) => {
      const row = document.createElement("div");
      row.className = gate.passed ? "passed" : "pending";
      addText(row, "strong", gate.name.replaceAll("_", " "));
      addText(row, "span", gate.passed ? "Passed" : gate.name === "editorial_review" ? "Pending editor" : "Blocked");
      addText(row, "p", gate.summary);
      gates.appendChild(row);
    });
    detail.appendChild(gates);

    addText(detail, "h3", "Method and limitations");
    item.research_record.methodology.forEach((stage) => addText(detail, "p", `${stage.stage}: ${stage.summary}`));
    const limitations = document.createElement("ul");
    item.research_record.limitations.forEach((value) => addText(limitations, "li", value));
    detail.appendChild(limitations);

    addText(detail, "h3", "Reviewed article Markdown");
    addText(detail, "pre", item.markdown, "editor-markdown");
    if (item.status === "draft") {
      const actions = document.createElement("div");
      actions.className = "editor-actions";
      const publish = addText(actions, "button", "Publish revision", "button primary");
      publish.type = "button";
      publish.addEventListener("click", async () => {
        await api(`/v1/admin/publications/${encodeURIComponent(bundleId)}/publish`, {method: "POST"});
        status.textContent = "Revision published and audit event recorded.";
        await loadQueue();
        await loadDetail(bundleId);
      });
      const reject = addText(actions, "button", "Reject revision", "button reject");
      reject.type = "button";
      reject.addEventListener("click", async () => {
        const reason = window.prompt("Record the editorial reason for rejection:");
        if (!reason) return;
        await api(`/v1/admin/publications/${encodeURIComponent(bundleId)}/reject`,
                  {method: "POST", body: JSON.stringify({reason})});
        status.textContent = "Revision rejected and audit event recorded.";
        await loadQueue();
        await loadDetail(bundleId);
      });
      detail.appendChild(actions);
    } else if (item.status === "published") {
      const actions = document.createElement("div");
      actions.className = "editor-actions";
      const retract = addText(actions, "button", "Retract publication", "button reject");
      retract.type = "button";
      retract.addEventListener("click", async () => {
        const reason = window.prompt("Record the public reason for retraction:");
        if (!reason) return;
        await api(`/v1/admin/publications/${encodeURIComponent(bundleId)}/retract`,
                  {method: "POST", body: JSON.stringify({reason})});
        status.textContent = "Publication retracted; the public record is retained.";
        await loadQueue();
        await loadDetail(bundleId);
      });
      detail.appendChild(actions);
    }
  };

  const loadQueue = async () => {
    const payload = await api("/v1/admin/publications");
    queue.replaceChildren();
    payload.publications.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      addText(button, "strong", item.title);
      addText(button, "span", `Revision ${item.revision} · ${item.status}`);
      button.addEventListener("click", () => loadDetail(item.bundle_id).catch(showError));
      queue.appendChild(button);
    });
    if (!payload.publications.length) addText(queue, "p", "No publication revisions are awaiting review.");
  };

  const showError = (error) => { status.textContent = error.message; };
  const initialize = async () => {
    try {
      const identity = await fetch("/v1/auth/session").then((response) => response.json());
      if (!identity.authenticated || !["editor", "admin"].includes(identity.role)) {
        throw new Error("Your session does not have editorial access.");
      }
      csrfToken = identity.csrf_token;
      await loadQueue();
      workspace.hidden = false;
      status.textContent = "Authenticated editorial queue loaded.";
    } catch (error) {
      showError(error);
    }
  };
  initialize();
});
