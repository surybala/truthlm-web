document.addEventListener("DOMContentLoaded", () => {
  const rail = document.querySelector("[data-investigation-rail]");
  const previous = document.querySelector("[data-investigation-previous]");
  const next = document.querySelector("[data-investigation-next]");
  if (!rail || !previous || !next) return;

  const scrollByCard = (direction) => {
    const card = rail.querySelector(".article-card");
    if (!card) return;
    const gap = Number.parseFloat(getComputedStyle(rail).columnGap || "0");
    rail.scrollBy({left: direction * (card.getBoundingClientRect().width + gap), behavior: "smooth"});
  };

  previous.addEventListener("click", () => scrollByCard(-1));
  next.addEventListener("click", () => scrollByCard(1));
});
