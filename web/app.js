// Sama domain kuin sivu
const API_BASE = "";

//

const dateInput = document.getElementById("dateInput");
const loadBtn = document.getElementById("loadBtn");
const statusEl = document.getElementById("status");
const ctx = document.getElementById("energyChart").getContext("2d");

let chart = null;
let availableDataRange = { startDate: null, endDate: null };

const today = new Date().toISOString().slice(0, 10);

function formatFinnishDate(isoDate) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate || "");
  return match ? `${match[3]}.${match[2]}.${match[1]}` : null;
}

function dateIsAvailable(date) {
  const { startDate, endDate } = availableDataRange;
  return !startDate || !endDate || (date >= startDate && date <= endDate);
}

function validateSelectedDate(date) {
  if (date && !dateIsAvailable(date)) {
    statusEl.textContent = "Valitulta ajankohdalta ei ole dataa saatavilla!";
    return false;
  }
  return true;
}

async function loadAvailableDateRange() {
  const resp = await fetch(`${API_BASE}/api/energy/date-range`);
  if (!resp.ok) throw new Error("API error: " + resp.status);

  const range = await resp.json();
  const startDate = range.start_date || null;
  const endDate = range.end_date || null;
  availableDataRange = { startDate, endDate };

  const rangeEl = document.getElementById("availableDataRange");
  const start = formatFinnishDate(startDate);
  const end = formatFinnishDate(endDate);
  rangeEl.textContent = start && end
    ? `(dataa saatavilla ${start} – ${end})`
    : "(dataa ei ole saatavilla)";

  if (startDate && endDate) {
    dateInput.min = startDate;
    dateInput.max = endDate;
    dateInput.value = today < startDate ? startDate : today > endDate ? endDate : today;
  } else {
    dateInput.value = today;
  }
}

async function loadData() {
  const date = dateInput.value;
  if (!date) {
    alert("Valitse päivä");
    return;
  }
  if (!validateSelectedDate(date)) return;

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
dateInput.addEventListener("change", function () {
  if (validateSelectedDate(dateInput.value)) statusEl.textContent = "";
});

async function initializePage() {
  try {
    await loadAvailableDateRange();
    await loadData();
  } catch (err) {
    console.error(err);
    dateInput.value = today;
    statusEl.textContent = "Virhe data-alueen latauksessa: " + err.message;
  }
}

initializePage();
