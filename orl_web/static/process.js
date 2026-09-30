document.addEventListener("DOMContentLoaded", () => {
  const player = document.querySelector(".process-player");
  if (!player) return;
  const toggle = player.querySelector(".process-toggle");
  const replay = player.querySelector(".process-replay");
  const narration = player.querySelector(".process-narration p");
  const messages = [
    "The question is scoped before the research begins.",
    "The research director gives independent assignments to domain experts.",
    "Experts retrieve and evaluate the most relevant scientific evidence.",
    "The language model builds a synthesis anchored to that evidence.",
    "Experts challenge the draft, revise weak points, and re-check the work through multiple rounds.",
    "The answer is delivered only after the material issues have been resolved or clearly disclosed."
  ];
  let stage = 0;
  let timer = null;
  let paused = false;

  const show = (next) => {
    stage = next;
    player.dataset.stage = String(stage);
    narration.textContent = messages[stage];
  };

  const schedule = () => {
    clearInterval(timer);
    if (paused) return;
    timer = setInterval(() => show((stage + 1) % messages.length), 2400);
  };

  toggle.addEventListener("click", () => {
    paused = !paused;
    player.classList.toggle("is-paused", paused);
    toggle.title = paused ? "Play" : "Pause";
    toggle.setAttribute("aria-label", paused ? "Play animation" : "Pause animation");
    schedule();
  });

  replay.addEventListener("click", () => {
    paused = false;
    player.classList.remove("is-paused");
    toggle.title = "Pause";
    toggle.setAttribute("aria-label", "Pause animation");
    show(0);
    schedule();
  });

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    paused = true;
    player.classList.add("is-paused");
    toggle.title = "Play";
    toggle.setAttribute("aria-label", "Play animation");
  }
  schedule();
});
