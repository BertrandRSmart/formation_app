(function () {
  function setRowVisible(inputEl, visible) {
    if (!inputEl) return;
    const row = inputEl.closest(".form-row") || inputEl.closest(".fieldBox") || inputEl.parentElement;
    if (!row) return;
    row.style.display = visible ? "" : "none";
  }

  function applyLocationRules() {
    const onClient = document.getElementById("id_on_client_site");
    const room = document.getElementById("id_room");
    const addr = document.getElementById("id_client_address");

    if (!onClient) return;

    if (onClient.checked) {
      // Chez le client: afficher adresse, cacher salle + vider salle
      setRowVisible(addr, true);
      setRowVisible(room, false);
      if (room) room.value = "";
    } else {
      // En salle: afficher salle, cacher adresse + vider adresse
      setRowVisible(room, true);
      setRowVisible(addr, false);
      if (addr) addr.value = "";
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyLocationRules();

    const onClient = document.getElementById("id_on_client_site");
    if (onClient) {
      onClient.addEventListener("change", applyLocationRules);
    }
  });
})();
