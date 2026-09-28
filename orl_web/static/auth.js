document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("login-form");
  if (!form) return;
  const email = document.getElementById("login-email");
  const status = document.getElementById("login-status");
  const button = form.querySelector("button[type='submit']");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    status.textContent = "Requesting a secure sign-in link...";
    try {
      const response = await fetch("/v1/auth/magic-link", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({email: email.value, next: form.dataset.next || "/questions"})
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.[0]?.msg || payload.detail || "Unable to request a link");
      form.classList.add("sent");
      email.disabled = true;
      status.textContent = payload.message;
      button.textContent = "Link requested";
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
  });
});
