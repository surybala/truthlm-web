document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("join-form");
  if (!form) return;
  const status = document.getElementById("join-status");
  const button = form.querySelector("button[type='submit']");
  const value = (name) => form.elements[name].value.trim();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!value("name") || !form.elements.email.checkValidity() || !value("email")) {
      status.textContent = "Please enter your name and a valid email address.";
      return;
    }
    button.disabled = true;
    status.textContent = "Sending your request...";
    try {
      const response = await fetch("/v1/access-requests", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: value("name"), email: value("email"), role: form.elements.role.value,
                              discipline: value("discipline"), note: value("note")})
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = Array.isArray(payload.detail) ? payload.detail[0]?.msg : payload.detail;
        throw new Error((detail || "We could not send your request. Please try again.").replace(/^Value error, /, ""));
      }
      form.classList.add("sent");
      Array.from(form.elements).forEach((element) => { element.disabled = true; });
      button.textContent = "Request received";
      status.textContent = payload.message;
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
  });
});
