// Sama domain kuin sivu
const API_BASE = "";

//

const dateInput = document.getElementById("dateInput");
const loadBtn = document.getElementById("loadBtn");
const statusEl = document.getElementById("status");
const ctx = document.getElementById("energyChart").getContext("2d");

let chart = null;

// Oletuksena tanaan
const today = new Date().toISOString().slice(0, 10);
dateInput.value = today;

async function loadData() {
  const date = dateInput.value;
  if (!date) {
    alert("Valitse paiva");
    return;
  }

  statusEl.textContent = "Ladataan dataa...";

  try {
    const url = `${API_BASE}/api/energy/quarter-hour?date=${encodeURIComponent(date)}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error("API error: " + resp.status);
    }
    const data = await resp.json();

    // Muodostetaan x-akselille kellonaika (HH:MM) ja y-akselille delta_kwh
    const labels = data.map(item => {
      const t = new Date(item.time);
      return t.toTimeString().slice(0, 5); // HH:MM
    });

    const values = data.map(item => item.delta_kwh);

    if (chart) {
      chart.destroy();
    }

    chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: `Kulutus ${date} (kWh / 15min)`,
          data: values,
          fill: false
        }]
      },
      options: {
        responsive: true,
        scales: {
          y: {
            title: {
              display: true,
              text: 'kWh / 15 min'
            }
          },
          x: {
            title: {
              display: true,
              text: 'Aika'
            }
          }
        }
      }
    });

    statusEl.textContent = `Ladattu ${data.length} pistetta paivalle ${date}`;
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Virhe datan latauksessa: " + err.message;
  }
}

loadBtn.addEventListener("click", loadData);

// Ladataan heti aluksi
loadData();
