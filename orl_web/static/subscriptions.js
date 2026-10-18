document.addEventListener("DOMContentLoaded", () => {
  const selected = document.getElementById("selected-subscriptions");
  if (!selected) return;
  const status = document.getElementById("subscription-status");
  const domainOptions = document.getElementById("domain-options");
  const researcherOptions = document.getElementById("researcher-options");
  const generate = document.getElementById("generate-feed");
  const revoke = document.getElementById("revoke-feed");
  const result = document.getElementById("personal-feed-result");
  const personalUrl = document.getElementById("personal-feed-url");
  const emailState = document.getElementById("email-state");
  const emailToggle = document.getElementById("email-toggle");
  let csrfToken = "";
  let state = {subscriptions: [], options: {domains: [], researchers: []}, personal_feed_active: false,
               email_enabled: true};

  const api = async (path, options = {}) => {
    const response = await fetch(path, {...options, headers: {
      "Content-Type": "application/json", "X-CSRF-Token": csrfToken, ...(options.headers || {})
    }});
    const payload = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `Request failed (${response.status})`);
    return payload;
  };

  const addText = (parent, tag, value, className = "") => {
    const element = document.createElement(tag);
    element.textContent = value;
    if (className) element.className = className;
    parent.appendChild(element);
    return element;
  };

  const addSubscription = async (kind, value) => {
    await api("/v1/subscriptions", {method: "POST", body: JSON.stringify({kind, value})});
    status.textContent = `Following ${kind === "all" ? "all weekly research" : value}.`;
    await load();
  };

  const optionButton = (parent, kind, value) => {
    const active = state.subscriptions.some((item) => item.kind === kind && item.value.toLocaleLowerCase() === value.toLocaleLowerCase());
    if (active) return;
    const label = kind === "all" ? "All weekly research" : value;
    const button = addText(parent, "button", `+ ${label}`);
    button.type = "button";
    button.addEventListener("click", () => addSubscription(kind, value).catch(showError));
  };

  const render = () => {
    selected.replaceChildren();
    const all = state.subscriptions.find((item) => item.kind === "all");
    if (!all) optionButton(selected, "all", "all");
    state.subscriptions.forEach((item) => {
      const row = document.createElement("div");
      row.className = "subscription-row";
      addText(row, "span", item.kind, `subscription-kind ${item.kind}`);
      addText(row, "strong", item.value);
      const remove = addText(row, "button", "Remove");
      remove.type = "button";
      remove.addEventListener("click", async () => {
        await api(`/v1/subscriptions/items/${encodeURIComponent(item.subscription_id)}`, {method: "DELETE"});
        status.textContent = `Stopped following ${item.value}.`;
        await load();
      });
      selected.appendChild(row);
    });
    if (!state.subscriptions.length) addText(selected, "p", "Choose all research or add at least one interest.", "empty-options");

    domainOptions.replaceChildren();
    state.options.domains.forEach((value) => optionButton(domainOptions, "domain", value));
    if (!domainOptions.children.length) addText(domainOptions, "p", "No additional published domains yet.", "empty-options");
    researcherOptions.replaceChildren();
    state.options.researchers.forEach((value) => optionButton(researcherOptions, "researcher", value));
    if (!researcherOptions.children.length) addText(researcherOptions, "p", "No additional cited researchers yet.", "empty-options");
    generate.textContent = state.personal_feed_active ? "Rotate personal feed URL" : "Create personal feed URL";
    revoke.hidden = !state.personal_feed_active;
    emailState.textContent = state.email_enabled
      ? (state.subscriptions.length ? "New investigations that match your interests are emailed to you."
        : "Email is on, but you follow nothing yet. Choose all research or add an interest below.")
      : "Research emails are off. You can still read everything on the site.";
    emailToggle.textContent = state.email_enabled ? "Stop research emails" : "Email me new research";
    emailToggle.className = state.email_enabled ? "button quiet" : "button dark";
    emailToggle.hidden = false;
  };

  const load = async () => {
    state = await api("/v1/subscriptions");
    render();
    if (!status.dataset.ready) {
      status.textContent = state.personal_feed_active ? "Your personal feed is active." : "Choose interests, then create your feed URL.";
      status.dataset.ready = "true";
    }
  };
  const showError = (error) => { status.textContent = error.message; };

  document.querySelectorAll(".interest-form").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = form.querySelector("input");
    try {
      await addSubscription(form.dataset.kind, input.value);
      input.value = "";
    } catch (error) { showError(error); }
  }));

  document.querySelectorAll(".copy-feed").forEach((button) => button.addEventListener("click", async () => {
    const input = document.getElementById(button.dataset.copy);
    try {
      await navigator.clipboard.writeText(input.value);
      button.textContent = "Copied";
      setTimeout(() => { button.textContent = "Copy feed URL"; }, 1200);
    } catch (_) {
      input.select();
      status.textContent = "Feed URL selected. Copy it from the field.";
    }
  }));

  emailToggle.addEventListener("click", async () => {
    try {
      const payload = await api("/v1/subscriptions/email", {method: "PUT",
        body: JSON.stringify({enabled: !state.email_enabled})});
      status.textContent = payload.email_enabled ? "Research emails are on." : "Research emails are off.";
      await load();
    } catch (error) { showError(error); }
  });

  generate.addEventListener("click", async () => {
    if (!state.subscriptions.length) {
      status.textContent = "Choose all weekly research or add an interest first.";
      return;
    }
    try {
      const payload = await api("/v1/subscriptions/feed-token", {method: "POST"});
      personalUrl.value = payload.feed_url;
      result.hidden = false;
      status.textContent = state.personal_feed_active ? "Old feed URL revoked. Add the new URL to your reader." : "Personal feed created.";
      await load();
    } catch (error) { showError(error); }
  });

  revoke.addEventListener("click", async () => {
    try {
      await api("/v1/subscriptions/feed-token", {method: "DELETE"});
      result.hidden = true;
      status.textContent = "Personal feed URL revoked.";
      status.dataset.ready = "true";
      await load();
    } catch (error) { showError(error); }
  });

  fetch("/v1/auth/session").then((response) => response.json()).then((identity) => {
    if (!identity.authenticated) throw new Error("Sign in to manage subscriptions.");
    csrfToken = identity.csrf_token;
    return load();
  }).catch(showError);
});
