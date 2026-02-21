(function () {
  function updateTrainingChoices(trainingTypeId, selectedTrainingId) {
    const trainingSelect = document.getElementById("id_training");
    if (!trainingSelect) return;

    // Vide la liste
    trainingSelect.innerHTML = "";

    // Option par défaut
    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "---------";
    trainingSelect.appendChild(emptyOpt);

    if (!trainingTypeId) return;

    fetch(`/api/trainings/?training_type_id=${trainingTypeId}`)
      .then((r) => r.json())
      .then((data) => {
        data.forEach((item) => {
          const opt = document.createElement("option");
          opt.value = item.id;
          opt.textContent = item.title;
          if (selectedTrainingId && String(item.id) === String(selectedTrainingId)) {
            opt.selected = true;
          }
          trainingSelect.appendChild(opt);
        });
      })
      .catch((err) => {
        console.error("Erreur chargement trainings:", err);
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const trainingTypeSelect = document.getElementById("id_training_type");
    const trainingSelect = document.getElementById("id_training");
    if (!trainingTypeSelect || !trainingSelect) return;

    // Si on est en édition, Django a déjà une valeur training ; on la conserve
    const currentTrainingId = trainingSelect.value;

    // Au chargement : si training_type est déjà choisi, on charge la liste filtrée
    if (trainingTypeSelect.value) {
      updateTrainingChoices(trainingTypeSelect.value, currentTrainingId);
    }

    // Quand on change le type : on recharge la liste et on efface le training choisi
    trainingTypeSelect.addEventListener("change", function () {
      updateTrainingChoices(trainingTypeSelect.value, null);
    });
  });
})();
