// -------------------------------------------
// P L O T L Y   S A N K E Y
// -------------------------------------------

// Lokalisointikartta Sankey-solmuille.
function localizeNode(name) {
  if (!name) return name;

  if (name === "PV") return "Aurinkosähkön tuotanto";
  if (name === "Export") return "Myynti verkkoon";
  if (name === "Grid") return "Ostosähkö";
  if (name === "CommunityUse") return "Kohdistamaton PV (BN02 puuttuu)";
  if (name === "Common" || name === "COMMON_MAIN") return "Yhteiset tilat";

  if (name.startsWith("APT")) {
    return `Asunto ${name.replace("APT", "")}`;
  }

  return name;
}

const energyFormatter = new Intl.NumberFormat("fi-FI", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

// Puuttuvaa tai virheellistä arvoa ei näytetä nollana.
function formatKwh(value) {
  if (value === null || value === undefined || value === "") return "–";

  const number = Number(value);
  return Number.isFinite(number) ? energyFormatter.format(number) : "–";
}

function renderDailyMeta(data) {
  const metaEl = document.getElementById("sankeyMeta");
  if (!metaEl) return;

  const meta = data.meta || {};

  metaEl.textContent =
    "Päivä: " + data.date + "  |  " +
    "PV: " + formatKwh(meta.pv_kwh) + " kWh  |  " +
    "PV yhteisiin tiloihin: " + formatKwh(meta.pv_to_common_kwh) + " kWh  |  " +
    "PV asuntoihin (arvio 1/24): " + formatKwh(meta.pv_to_apartments_kwh) + " kWh  |  " +
    "Yhteisten tilojen ostosähkö: " + formatKwh(meta.common_load_kwh) + " kWh  |  " +
    "Asuntojen ostosähkö: " + formatKwh(meta.apartments_load_kwh) + " kWh  |  " +
    "Grid: " + formatKwh(meta.grid_to_load_kwh) + " kWh  |  " +
    "Export: " + formatKwh(meta.pv_export_kwh) + " kWh" +
    (Number(meta.internal_consumption_kwh || 0) > 0
      ? "  |  Sisäiset kulutusalamittaukset: " +
        formatKwh(meta.internal_consumption_kwh) + " kWh"
      : "") +
    (Number(meta.pv_unallocated_kwh || 0) > 0
      ? "  |  Kohdistamaton PV: " + formatKwh(meta.pv_unallocated_kwh) + " kWh"
      : "");
}

let currentAnnual = null;
const euroFormatter = new Intl.NumberFormat("fi-FI", { style: "currency", currency: "EUR" });
const priceFormatter = new Intl.NumberFormat("fi-FI", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function annualEnergy(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function renderAnnualPrices() {
  const purchase = Number(document.getElementById("purchasePrice").value);
  const sale = Number(document.getElementById("salePrice").value);
  document.getElementById("purchasePriceValue").textContent = priceFormatter.format(purchase) + " snt/kWh";
  document.getElementById("salePriceValue").textContent = priceFormatter.format(sale) + " snt/kWh";
  const show = (id, energy, price) => {
    document.getElementById(id).textContent = energy === null ? "–" :
      formatKwh(energy) + " kWh · " + euroFormatter.format(energy * price / 100);
  };
  for (const group of ["common", "apartments"]) {
    const values = currentAnnual?.[group];
    show(group + "PurchaseCost", annualEnergy(values?.grid_kwh), purchase);
    show(group + "SolarSavings", annualEnergy(values?.self_used_pv_kwh), purchase);
    show(group + "SaleCredit", annualEnergy(values?.export_kwh), sale);
  }
  document.getElementById("annualSplitNotice").textContent = currentAnnual?.pv_split_complete === false
    ? "Aurinkosähkön vuosijakoa ja säästöjä ei voida laskea: osasta mittausvälejä puuttuu PV-/BN02-/BN03-tietoja tai niiden arvot ovat ristiriidassa."
    : "";
}

function renderAnnualMeta(data) {
  const annualEl = document.getElementById("sankeyAnnualMeta");
  if (!annualEl) return;

  const annual = data.annual;
  currentAnnual = annual || null;
  renderAnnualPrices();

  if (!annual) {
    annualEl.textContent = "Vuositietoja ei ole saatavilla.";
    return;
  }

  const year = annual.year || String(data.date || "").slice(0, 4);

  annualEl.textContent = "Vuosi " + year + "  |  Aurinkosähkön kokonaistuotanto: " +
    formatKwh(annual.pv_kwh) + " kWh";

}

let latestSankeyRequest = 0;

async function loadSankey(dateStr) {
  const requestId = ++latestSankeyRequest;
  currentAnnual = null;
  renderAnnualPrices();
  const metaEl = document.getElementById("sankeyMeta");
  const annualEl = document.getElementById("sankeyAnnualMeta");

  console.log("Ladataan Sankey päivälle:", dateStr);

  try {
    const url = "/api/sankey?date=" + encodeURIComponent(dateStr);
    console.log("Fetch:", url);

    const resp = await fetch(url);
    if (requestId !== latestSankeyRequest) return;
    console.log("HTTP status:", resp.status);

    if (!resp.ok) {
      const message = "Virhe: " + resp.status + " " + resp.statusText;
      if (metaEl) metaEl.textContent = message;
      if (annualEl) annualEl.textContent = "";
      return;
    }

    const data = await resp.json();
    if (requestId !== latestSankeyRequest) return;
    console.log("Saatiin data:", data);

    if (!Array.isArray(data.nodes) || !Array.isArray(data.links)) {
      if (metaEl) metaEl.textContent = "Virhe: vastauksessa ei ole nodes/link-dataa";
      if (annualEl) annualEl.textContent = "";
      return;
    }

    renderDailyMeta(data);
    renderAnnualMeta(data);

    const labels = data.nodes.map(localizeNode);
    const sources = data.links.map(link => link.source);
    const targets = data.links.map(link => link.target);
    const values = data.links.map(link => link.value);

    function isPVLink(link) {
      return data.nodes[link.source] === "PV";
    }

    const linkColors = data.links.map(link =>
      isPVLink(link) ? "rgba(255,215,0,1.0)" : "rgba(120,140,180,0.12)"
    );

    const nodeColors = data.nodes.map(node => {
      if (node === "PV") return "rgba(255,215,0,1.0)";
      if (node === "Grid") return "rgba(80,140,220,0.45)";
      if (node === "Export") return "rgba(120,120,120,0.35)";
      if (node === "Common" || node === "COMMON_MAIN") return "rgba(160,170,190,0.35)";
      if (node === "CommunityUse") return "rgba(220,160,60,0.40)";
      return "rgba(160,170,190,0.25)";
    });

    const chartEl = document.getElementById("sankeyChart");

    if (!chartEl) {
      console.error("Ei löytynyt sankeyChart-elementtiä.");
      if (metaEl) metaEl.textContent = "Virhe: Sankey-alue puuttuu sivulta.";
      return;
    }

    const trace = {
      type: "sankey",
      arrangement: "snap",
      node: {
        label: labels,
        color: nodeColors,
        pad: 14,
        thickness: 18,
        line: { color: "rgba(0,0,0,0.15)", width: 1 }
      },
      link: {
        source: sources,
        target: targets,
        value: values,
        color: linkColors
      }
    };

    const layout = {
      margin: { l: 10, r: 10, t: 10, b: 10 },
      font: { size: 12 }
    };

    Plotly.react(chartEl, [trace], layout, { responsive: true });
  } catch (err) {
    if (requestId !== latestSankeyRequest) return;
    currentAnnual = null;
    renderAnnualPrices();
    console.error("Poikkeus loadSankey-funktiossa:", err);
    if (metaEl) metaEl.textContent = "Virhe haettaessa Sankey-dataa.";
    if (annualEl) annualEl.textContent = "";
  }
}

function showSummary(period) {
  const annual = period === "annual";
  document.getElementById("dailySummary").hidden = annual;
  document.getElementById("annualPrices").hidden = !annual;
  document.getElementById("showDaily").setAttribute("aria-pressed", String(!annual));
  document.getElementById("showAnnual").setAttribute("aria-pressed", String(annual));
}

document.addEventListener("DOMContentLoaded", function () {
  console.log("DOMContentLoaded, asetetaan painike ja oletuspäivä");

  const dateInput = document.getElementById("sankeyDate");
  const button = document.getElementById("sankeyLoadBtn");
  const defaultDate = "2025-09-01";

  document.getElementById("showDaily").addEventListener("click", () => showSummary("daily"));
  document.getElementById("showAnnual").addEventListener("click", () => showSummary("annual"));
  showSummary("daily");

  if (dateInput) dateInput.value = defaultDate;

  if (button) {
    button.addEventListener("click", function () {
      const date = dateInput ? dateInput.value : "";

      if (!date) {
        alert("Valitse päivämäärä");
        return;
      }

      loadSankey(date);
    });
  }

  for (const id of ["purchasePrice", "salePrice"]) {
    document.getElementById(id).addEventListener("input", renderAnnualPrices);
  }

  loadSankey(defaultDate);
});
