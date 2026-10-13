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

function formatFinnishDate(isoDate) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate || "");
  return match ? `${match[3]}.${match[2]}.${match[1]}` : null;
}

let availableDataRange = { startDate: null, endDate: null };

function renderAvailableDataRange(data) {
  const rangeEl = document.getElementById("availableDataRange");
  if (!rangeEl) return;

  const startDate = data?.available_data?.start_date || null;
  const endDate = data?.available_data?.end_date || null;
  const start = formatFinnishDate(startDate);
  const end = formatFinnishDate(endDate);
  const dateInput = document.getElementById("sankeyDate");
  availableDataRange = { startDate, endDate };

  if (dateInput && startDate && endDate) {
    dateInput.min = startDate;
    dateInput.max = endDate;
  } else if (dateInput) {
    dateInput.removeAttribute("min");
    dateInput.removeAttribute("max");
  }

  rangeEl.textContent = start && end
    ? `(dataa saatavilla ${start} – ${end})`
    : "(dataa ei ole saatavilla)";
  if (dateInput?.value) validateSelectedDate(dateInput.value);
}

function dateIsAvailable(date) {
  const { startDate, endDate } = availableDataRange;
  return !startDate || !endDate || (date >= startDate && date <= endDate);
}

function validateSelectedDate(date) {
  const statusEl = document.getElementById("dateStatus");
  if (date && !dateIsAvailable(date)) {
    statusEl.textContent = "Valitulta ajankohdalta ei ole dataa saatavilla!";
    return false;
  }
  statusEl.textContent = "";
  return true;
}

function apartmentNumber(nodeName) {
  const match = /^APT(\d+)$/.exec(nodeName || "");
  return match ? Number(match[1]) : null;
}

// Plotly voi muuten järjestää saman sarakkeen solmut linkkien painojen mukaan.
// Annetaan sille asuntojen numeerista järjestystä vastaavat aloituspaikat.
function sankeyNodePositions(nodes) {
  const sources = new Set(["PV", "Grid"]);
  const targetNodes = nodes.filter(node => !sources.has(node));
  const fixedTargets = targetNodes.filter(node => apartmentNumber(node) === null);
  const apartments = targetNodes
    .filter(node => apartmentNumber(node) !== null)
    .sort((left, right) => apartmentNumber(left) - apartmentNumber(right));
  const orderedTargets = [...fixedTargets, ...apartments];
  const targetRank = new Map(
    orderedTargets.map((node, position) => [node, position])
  );
  const lastTarget = Math.max(orderedTargets.length - 1, 1);

  return {
    x: nodes.map(node => sources.has(node) ? 0.02 : 0.82),
    y: nodes.map(node => {
      if (node === "PV") return 0.02;
      if (node === "Grid") return 0.58;
      return 0.02 + 0.96 * targetRank.get(node) / lastTarget;
    }),
    targetCount: orderedTargets.length
  };
}

let currentDaily = null;
let currentDailyIncomplete = false;

function renderDailyMeta(data) {
  const metaEl = document.getElementById("sankeyMeta");
  if (!metaEl) return;

  const meta = data.meta || {};
  const selectedDate = formatFinnishDate(data.date) || data.date;
  const hourly = data.period === "hour";
  const hour = Number(data.hour);
  const hourRange = Number.isInteger(hour)
    ? `${String(hour).padStart(2, "0")}.00–${String(hour + 1).padStart(2, "0")}.00`
    : "";
  const unallocated = Number(meta.pv_unallocated_kwh || 0);
  const missingIntervals = Number(meta.intervals_without_bn02 || 0);
  const incompleteSplit = unallocated > 0 || missingIntervals > 0;
  currentDaily = meta;
  currentDailyIncomplete = incompleteSplit;

  document.getElementById("dailySummaryTitle").textContent = hourly
    ? "Tunnin energiatiedot"
    : "Vuorokauden energiatiedot";
  document.getElementById("intervalPriceDescription").textContent = hourly
    ? "Arvio valitun tunnin energiasta käyttäen vakiohintoja."
    : "Arvio valitun vuorokauden energiasta käyttäen vakiohintoja.";

  metaEl.textContent = (hourly ? "Tunti " : "Päivä ") + selectedDate +
    (hourly ? " klo " + hourRange : "") +
    "  |  Aurinkosähkön kokonaistuotanto: " + formatKwh(meta.pv_kwh) + " kWh";

  renderDailyPrices();

  const notices = [];
  if (incompleteSplit) {
    notices.push(
      "Aurinkosähkön jako on osittainen: " + formatKwh(unallocated) +
      " kWh jäi kohdistamatta" +
      (missingIntervals > 0
        ? `, koska BN02-tietoja puuttui ${missingIntervals} mittausväliltä.`
        : ".")
    );
  }
  if (Number(meta.internal_consumption_kwh || 0) > 0) {
    notices.push(
      "Sisäisten kulutusalamittausten kulutus: " +
      formatKwh(meta.internal_consumption_kwh) + " kWh."
    );
  }
  document.getElementById("dailySplitNotice").textContent = notices.join(" ");
}

let currentAnnual = null;
const euroFormatter = new Intl.NumberFormat("fi-FI", { style: "currency", currency: "EUR" });
const priceFormatter = new Intl.NumberFormat("fi-FI", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function annualEnergy(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function renderDailyPrices() {
  const purchase = Number(document.getElementById("dailyPurchasePrice").value);
  const sale = Number(document.getElementById("dailySalePrice").value);
  document.getElementById("dailyPurchasePriceValue").textContent =
    priceFormatter.format(purchase) + " snt/kWh";
  document.getElementById("dailySalePriceValue").textContent =
    priceFormatter.format(sale) + " snt/kWh";

  const show = (id, energy, price, suffix = "") => {
    document.getElementById(id).textContent = energy === null ? "–" :
      formatKwh(energy) + " kWh · " +
      euroFormatter.format(energy * price / 100) + suffix;
  };
  const suffix = currentDailyIncomplete ? " (tiedot puutteelliset)" : "";

  show("dailyCommonGrid", annualEnergy(currentDaily?.common_load_kwh), purchase);
  show("dailyCommonSolar", annualEnergy(currentDaily?.pv_to_common_kwh), purchase, suffix);
  show("dailyCommonExport", annualEnergy(currentDaily?.pv_export_kwh), sale);
  show("dailyApartmentsGrid", annualEnergy(currentDaily?.apartments_load_kwh), purchase);
  show("dailyApartmentsSolar", annualEnergy(currentDaily?.pv_to_apartments_kwh), purchase, suffix);
  show("dailyApartmentsExport", currentDaily ? 0 : null, sale);
}

function renderAnnualPrices() {
  const purchase = Number(document.getElementById("purchasePrice").value);
  const sale = Number(document.getElementById("salePrice").value);
  document.getElementById("purchasePriceValue").textContent = priceFormatter.format(purchase) + " snt/kWh";
  document.getElementById("salePriceValue").textContent = priceFormatter.format(sale) + " snt/kWh";
  const show = (id, energy, price, suffix = "") => {
    document.getElementById(id).textContent = energy === null ? "–" :
      formatKwh(energy) + " kWh · " + euroFormatter.format(energy * price / 100) + suffix;
  };
  const incompleteSplit = currentAnnual?.pv_split_complete === false;
  for (const group of ["common", "apartments"]) {
    const values = currentAnnual?.[group];
    show(group + "PurchaseCost", annualEnergy(values?.grid_kwh), purchase);
    show(
      group + "SolarSavings",
      annualEnergy(values?.self_used_pv_kwh),
      purchase,
      incompleteSplit ? " (tiedot puutteelliset)" : ""
    );
    show(group + "SaleCredit", annualEnergy(values?.export_kwh), sale);
  }
  if (incompleteSplit) {
    const included = Number(currentAnnual?.pv_split_included_intervals);
    const excluded = Number(currentAnnual?.pv_split_excluded_intervals);
    const coverage = Number.isFinite(included) && Number.isFinite(excluded)
      ? ` Mukana ${included} mittausväliä, ohitettu ${excluded}.`
      : "";
    document.getElementById("annualSplitNotice").textContent =
      "Aurinkosähkön jako ja säästö ovat osittaisia: laskennassa ovat mukana vain mittausvälit, joiden PV-, BN02- ja BN03-tiedot ovat täydelliset ja keskenään johdonmukaiset." + coverage;
  } else {
    document.getElementById("annualSplitNotice").textContent = "";
  }
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
let selectedPeriod = "day";

async function loadSankey(dateStr) {
  if (!validateSelectedDate(dateStr)) return;

  const period = selectedPeriod;
  const chartEl = document.getElementById("sankeyChart");
  const chartTitle = document.getElementById("sankeyChartTitle");
  chartEl.hidden = true;
  chartTitle.textContent = "Ladataan kaaviota…";
  const requestId = ++latestSankeyRequest;
  currentDaily = null;
  currentDailyIncomplete = false;
  renderDailyPrices();
  currentAnnual = null;
  renderAnnualPrices();
  const metaEl = document.getElementById("sankeyMeta");
  const annualEl = document.getElementById("sankeyAnnualMeta");

  console.log("Ladataan Sankey päivälle:", dateStr);

  try {
    const hour = document.getElementById("sankeyHour").value;
    const hourParameter = period === "hour" ? "&hour=" + encodeURIComponent(hour) : "";
    const url = "/api/sankey?date=" + encodeURIComponent(dateStr) +
      "&period=" + period + hourParameter;
    console.log("Fetch:", url);

    const resp = await fetch(url);
    if (requestId !== latestSankeyRequest) return;
    console.log("HTTP status:", resp.status);

    if (!resp.ok) {
      chartTitle.textContent = "Kaavion lataus epäonnistui.";
      const message = "Virhe: " + resp.status + " " + resp.statusText;
      if (metaEl) metaEl.textContent = message;
      if (annualEl) annualEl.textContent = "";
      return;
    }

    const data = await resp.json();
    if (requestId !== latestSankeyRequest) return;
    console.log("Saatiin data:", data);
    renderAvailableDataRange(data);

    if (!Array.isArray(data.nodes) || !Array.isArray(data.links)) {
      chartTitle.textContent = "Kaavion lataus epäonnistui.";
      if (metaEl) metaEl.textContent = "Virhe: vastauksessa ei ole nodes/link-dataa";
      if (annualEl) annualEl.textContent = "";
      return;
    }

    if (period === "day" || period === "hour") renderDailyMeta(data);
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

    const nodePositions = sankeyNodePositions(data.nodes);

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
        x: nodePositions.x,
        y: nodePositions.y,
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
      height: Math.max(520, nodePositions.targetCount * 32 + 80),
      margin: { l: 10, r: 10, t: 10, b: 10 },
      font: { size: 12 }
    };

    chartEl.style.height = layout.height + "px";
    chartEl.hidden = false;
    if (period === "year") {
      chartTitle.textContent = "Vuoden " + dateStr.slice(0, 4) + " energiavirrat (kWh)";
    } else if (period === "hour") {
      const selectedHour = Number(data.hour);
      const hourRange = `${String(selectedHour).padStart(2, "0")}.00–` +
        `${String(selectedHour + 1).padStart(2, "0")}.00`;
      chartTitle.textContent = "Tunnin " + dateStr + " klo " + hourRange +
        " energiavirrat (kWh)";
    } else {
      chartTitle.textContent = "Päivän " + dateStr + " energiavirrat (kWh)";
    }
    Plotly.react(chartEl, [trace], layout, { responsive: true });
  } catch (err) {
    if (requestId !== latestSankeyRequest) return;
    chartTitle.textContent = "Kaavion lataus epäonnistui.";
    chartEl.hidden = true;
    currentAnnual = null;
    renderAnnualPrices();
    console.error("Poikkeus loadSankey-funktiossa:", err);
    if (metaEl) metaEl.textContent = "Virhe haettaessa Sankey-dataa.";
    if (annualEl) annualEl.textContent = "";
  }
}

function showSummary(view, reload = true) {
  const start = view === "start";
  const daily = view === "daily";
  const annual = view === "annual";
  const hourly = view === "hourly";
  selectedPeriod = annual ? "year" : hourly ? "hour" : "day";
  document.getElementById("hourControl").hidden = !hourly;
  document.getElementById("dailySummary").hidden = !(daily || hourly);
  document.getElementById("annualPrices").hidden = !annual;
  document.getElementById("showStart").setAttribute("aria-pressed", String(start));
  document.getElementById("showDaily").setAttribute("aria-pressed", String(daily));
  document.getElementById("showAnnual").setAttribute("aria-pressed", String(annual));
  document.getElementById("showHourly").setAttribute("aria-pressed", String(hourly));
  const date = document.getElementById("sankeyDate").value;
  if (reload && date) loadSankey(date);
}

document.addEventListener("DOMContentLoaded", function () {
  console.log("DOMContentLoaded, asetetaan painike ja oletuspäivä");

  const dateInput = document.getElementById("sankeyDate");
  const hourInput = document.getElementById("sankeyHour");
  const button = document.getElementById("sankeyLoadBtn");
  const defaultDate = "2025-09-01";

  for (let hour = 0; hour < 24; hour += 1) {
    const option = document.createElement("option");
    option.value = String(hour);
    option.textContent = `${String(hour).padStart(2, "0")}.00–` +
      `${String(hour + 1).padStart(2, "0")}.00`;
    hourInput.appendChild(option);
  }
  hourInput.value = "12";

  document.getElementById("showStart").addEventListener("click", () => showSummary("start"));
  document.getElementById("showDaily").addEventListener("click", () => showSummary("daily"));
  document.getElementById("showAnnual").addEventListener("click", () => showSummary("annual"));
  document.getElementById("showHourly").addEventListener("click", () => showSummary("hourly"));
  showSummary("start", false);

  if (dateInput) dateInput.value = defaultDate;

  if (button) {
    button.addEventListener("click", function () {
      const date = dateInput ? dateInput.value : "";

      if (!date) {
        alert("Valitse päivämäärä");
        return;
      }

      if (validateSelectedDate(date)) loadSankey(date);
    });
  }

  if (dateInput) {
    dateInput.addEventListener("change", function () {
      validateSelectedDate(dateInput.value);
    });
  }

  hourInput.addEventListener("change", function () {
    if (selectedPeriod === "hour" && dateInput?.value) {
      loadSankey(dateInput.value);
    }
  });

  for (const id of ["purchasePrice", "salePrice"]) {
    document.getElementById(id).addEventListener("input", renderAnnualPrices);
  }
  for (const id of ["dailyPurchasePrice", "dailySalePrice"]) {
    document.getElementById(id).addEventListener("input", renderDailyPrices);
  }

  loadSankey(defaultDate);
});
