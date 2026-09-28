document.addEventListener("DOMContentLoaded", () => {
  const tabs = Array.from(document.querySelectorAll("[data-tab]"));
  if (tabs.length) {
    const selectTab = (tab, updateHash = true) => {
      tabs.forEach((candidate) => {
        const active = candidate === tab;
        candidate.setAttribute("aria-selected", String(active));
        candidate.setAttribute("tabindex", active ? "0" : "-1");
        const panel = document.getElementById(candidate.dataset.tab);
        if (panel) panel.hidden = !active;
      });
      if (updateHash) history.replaceState(null, "", `#${tab.dataset.tab}`);
      tab.focus({ preventScroll: true });
    };
    tabs.forEach((tab, index) => {
      tab.setAttribute("tabindex", tab.getAttribute("aria-selected") === "true" ? "0" : "-1");
      tab.addEventListener("click", () => selectTab(tab));
      tab.addEventListener("keydown", (event) => {
        if (!(["ArrowLeft", "ArrowRight"].includes(event.key))) return;
        event.preventDefault();
        const offset = event.key === "ArrowRight" ? 1 : -1;
        selectTab(tabs[(index + offset + tabs.length) % tabs.length]);
      });
    });
    const requested = tabs.find((tab) => `#${tab.dataset.tab}` === window.location.hash);
    if (requested) selectTab(requested, false);
    document.querySelectorAll("[data-tab-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        const tab = tabs.find((candidate) => candidate.dataset.tab === link.dataset.tabLink);
        if (!tab) return;
        event.preventDefault();
        selectTab(tab);
        tab.scrollIntoView({behavior: "smooth", block: "start"});
      });
    });
  }

  document.querySelectorAll(".share-bar").forEach((bar) => {
    const status = bar.querySelector(".share-status");
    const {shareUrl: url, shareTitle: title, shareText: text} = bar.dataset;
    const native = bar.querySelector(".share-native");
    if (native && navigator.share) {
      native.hidden = false;
      native.addEventListener("click", () => navigator.share({title, text, url}).catch(() => {}));
    }
    bar.querySelector(".share-copy")?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(url);
        status.textContent = "Link copied";
      } catch (error) {
        status.textContent = url;
      }
    });
  });

  document.querySelectorAll(".account-menu").forEach((menu) => {
    document.addEventListener("click", (event) => {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      menu.removeAttribute("open");
      menu.querySelector("summary")?.focus();
    });
  });

  const logout = document.getElementById("logout-button");
  if (logout) logout.addEventListener("click", async () => {
    const session = await fetch("/v1/auth/session").then((response) => response.json());
    await fetch("/v1/auth/logout", {method: "POST", headers: {"X-CSRF-Token": session.csrf_token}});
    window.location.assign("/");
  });
});
