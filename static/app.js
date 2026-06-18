/* ============================================================
   AWS Cost Console
   ============================================================ */

var statusEl = document.getElementById("status");
var statusDot = document.getElementById("status-dot");
var countEl = document.getElementById("account-count");
var bodyEl = document.getElementById("accounts-body");
var searchEl = document.getElementById("search");
var showRolesEl = document.getElementById("show-roles");

var allAccounts = [];
var accountRoles = {};
var rolesLoaded = false;

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.className = "status" + (state ? " " + state : "");
  statusDot.className = "status-dot" + (state ? " " + state : "");
}
function showError(msg) { setStatus(msg, "error"); }

// ============================================================
// localStorage cache (client-side, 1 hour TTL)
// ============================================================
var CLIENT_CACHE_TTL = 60 * 60 * 1000; // 1 hour

function clientCacheGet(key) {
  try {
    var raw = localStorage.getItem("awscc:" + key);
    if (!raw) return null;
    var entry = JSON.parse(raw);
    if (Date.now() - entry.ts > CLIENT_CACHE_TTL) {
      localStorage.removeItem("awscc:" + key);
      return null;
    }
    return entry.data;
  } catch (e) { return null; }
}

function clientCacheSet(key, data) {
  try {
    localStorage.setItem("awscc:" + key, JSON.stringify({ data: data, ts: Date.now() }));
  } catch (e) { /* quota exceeded — ignore */ }
}

function clientCacheClear() {
  var keys = [];
  for (var i = 0; i < localStorage.length; i++) {
    var k = localStorage.key(i);
    if (k && k.startsWith("awscc:")) keys.push(k);
  }
  keys.forEach(function (k) { localStorage.removeItem(k); });
  return keys.length;
}

// ============================================================
// Tabs
// ============================================================
document.querySelectorAll(".tab").forEach(function (btn) {
  btn.addEventListener("click", function () {
    document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
    document.querySelectorAll(".tab-content").forEach(function (c) { c.classList.remove("active"); });
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab + "-tab").classList.add("active");
  });
});

// ============================================================
// Date Picker
// ============================================================
var MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

(function initDatePickers() {
  var now = new Date();
  var curYear = now.getFullYear();
  var curMonth = now.getMonth();
  var years = [];
  for (var y = curYear - 3; y <= curYear; y++) years.push(y);

  var configs = [
    { yearId: "cost-start-year", monthId: "cost-start-month", y: curYear, m: curMonth - 3 },
    { yearId: "cost-end-year", monthId: "cost-end-month", y: curYear, m: curMonth },
  ];
  configs.forEach(function (cfg) {
    var dy = cfg.y, dm = cfg.m;
    if (dm < 0) { dm += 12; dy -= 1; }
    var yel = document.getElementById(cfg.yearId);
    var mel = document.getElementById(cfg.monthId);
    years.forEach(function (y) {
      var o = document.createElement("option"); o.value = String(y); o.textContent = String(y);
      if (y === dy) o.selected = true; yel.appendChild(o);
    });
    for (var m = 0; m < 12; m++) {
      var o = document.createElement("option"); o.value = String(m+1).padStart(2,"0"); o.textContent = MONTHS[m];
      if (m === dm) o.selected = true; mel.appendChild(o);
    }
  });
})();

function getDateRange() {
  var sy = document.getElementById("cost-start-year").value;
  var sm = document.getElementById("cost-start-month").value;
  var ey = document.getElementById("cost-end-year").value;
  var em = document.getElementById("cost-end-month").value;
  var start = sy + "-" + sm + "-01";
  var endY = parseInt(ey), endM = parseInt(em) + 1;
  if (endM > 12) { endY++; endM = 1; }
  return { start: start, end: endY + "-" + String(endM).padStart(2,"0") + "-01" };
}

// ============================================================
// Accounts Tab
// ============================================================
async function loadAccounts() {
  try {
    var res = await fetch("/api/accounts");
    if (!res.ok) {
      var detail = (await res.json()).detail || "HTTP " + res.status;
      if (res.status === 401) { showErrorWithSsoHint(detail); } else { showError(detail); }
      return;
    }
    var data = await res.json();
    allAccounts = data.accounts;
    countEl.textContent = data.count;
    setStatus(data.count + " accounts loaded", "ok");
    populateAccountSelect();
    renderAccountsTable();
  } catch (e) { showError("Failed to fetch accounts: " + e.message); }
}

async function loadRoles() {
  if (rolesLoaded) return;
  setStatus("Loading roles...", "");
  try {
    var res = await fetch("/api/accounts/detail");
    if (!res.ok) {
      var detail = (await res.json()).detail || "HTTP " + res.status;
      if (res.status === 401) { showErrorWithSsoHint(detail); } else { showError(detail); }
      return;
    }
    var data = await res.json();
    data.accounts.forEach(function (a) { accountRoles[a.accountId] = a.roles; });
    rolesLoaded = true;
    setStatus(allAccounts.length + " accounts (with roles)", "ok");
    renderAccountsTable();
  } catch (e) { showError("Failed: " + e.message); }
}

function createCell(text, cls) {
  var td = document.createElement("td"); td.textContent = text; if (cls) td.className = cls; return td;
}
function createRoleTag(name) {
  var s = document.createElement("span"); s.className = "role-tag"; s.textContent = name; return s;
}
function createRolesCell(id) {
  var td = document.createElement("td"); td.className = "roles roles-col";
  var roles = accountRoles[id] || [];
  if (!roles.length) { var d = document.createElement("span"); d.style.color="var(--text-tertiary)"; d.textContent="\u2014"; td.appendChild(d); }
  else roles.forEach(function(r){ td.appendChild(createRoleTag(r)); td.appendChild(document.createTextNode(" ")); });
  return td;
}

function renderAccountsTable() {
  var q = searchEl.value.toLowerCase();
  var show = showRolesEl.checked;
  document.querySelectorAll(".roles-col").forEach(function(e){ e.classList.toggle("hidden",!show); });
  var filtered = allAccounts.filter(function(a){ return (a.accountName+" "+a.accountId+" "+a.emailAddress).toLowerCase().includes(q); });
  while (bodyEl.firstChild) bodyEl.removeChild(bodyEl.firstChild);
  filtered.forEach(function(a,i){
    var tr = document.createElement("tr");
    tr.appendChild(createCell(String(i+1)));
    tr.appendChild(createCell(a.accountName,"account-name"));
    tr.appendChild(createCell(a.accountId,"account-id"));
    tr.appendChild(createCell(a.emailAddress));
    if (show) tr.appendChild(createRolesCell(a.accountId));
    bodyEl.appendChild(tr);
  });
}

searchEl.addEventListener("input", renderAccountsTable);
showRolesEl.addEventListener("change", function(){ if(showRolesEl.checked&&!rolesLoaded)loadRoles(); renderAccountsTable(); });

// ============================================================
// Multi-Select
// ============================================================
var msToggle = document.getElementById("account-select-toggle");
var msDropdown = document.getElementById("account-select-dropdown");
var msOptions = document.getElementById("account-select-options");
var msSearch = document.getElementById("account-select-search");
var selectedAccountIds = new Set();

function populateAccountSelect() {
  while (msOptions.firstChild) msOptions.removeChild(msOptions.firstChild);
  allAccounts.forEach(function(a){
    var lbl = document.createElement("label"); lbl.className = "multi-select-option";
    lbl.dataset.searchText = (a.accountName+" "+a.accountId+" "+a.emailAddress).toLowerCase();
    var cb = document.createElement("input"); cb.type="checkbox"; cb.value=a.accountId; cb.checked=true;
    lbl.appendChild(cb); lbl.appendChild(document.createTextNode(a.accountName+" ("+a.accountId+")"));
    msOptions.appendChild(lbl);
  });
  selectedAccountIds = new Set(allAccounts.map(function(a){return a.accountId;}));
  updateToggleLabel();
}

function updateToggleLabel() {
  var t = allAccounts.length, s = selectedAccountIds.size;
  if (!s) msToggle.textContent = "No accounts selected";
  else if (s === t) msToggle.textContent = "All Accounts (" + t + ")";
  else if (s <= 3) msToggle.textContent = allAccounts.filter(function(a){return selectedAccountIds.has(a.accountId);}).map(function(a){return a.accountName;}).join(", ");
  else msToggle.textContent = s + " accounts selected";
}

msToggle.addEventListener("click", function(e){ e.stopPropagation(); msDropdown.classList.toggle("hidden"); if(!msDropdown.classList.contains("hidden")) msSearch.focus(); });
document.addEventListener("click", function(e){ if(!document.getElementById("account-select").contains(e.target)) msDropdown.classList.add("hidden"); });
msOptions.addEventListener("change", function(e){ if(e.target.type!=="checkbox")return; if(e.target.checked)selectedAccountIds.add(e.target.value); else selectedAccountIds.delete(e.target.value); updateToggleLabel(); });
document.getElementById("account-select-all").addEventListener("click", function(){ msOptions.querySelectorAll("input[type=checkbox]").forEach(function(c){c.checked=true;}); selectedAccountIds=new Set(allAccounts.map(function(a){return a.accountId;})); updateToggleLabel(); });
document.getElementById("account-deselect-all").addEventListener("click", function(){ msOptions.querySelectorAll("input[type=checkbox]").forEach(function(c){c.checked=false;}); selectedAccountIds.clear(); updateToggleLabel(); });
msSearch.addEventListener("input", function(){ var q=msSearch.value.toLowerCase(); msOptions.querySelectorAll(".multi-select-option").forEach(function(o){o.style.display=o.dataset.searchText.includes(q)?"":"none";}); });

// ============================================================
// Cost Metric
// ============================================================
var costMetricEl = document.getElementById("cost-metric");
var metricHelpBtn = document.getElementById("metric-help-btn");
var lastAccountResults = null;
var lastGranularity = null;

var METRIC_LABELS = {
  UnblendedCost: "Unblended Cost",
  AmortizedCost: "Amortized Cost",
  BlendedCost: "Blended Cost",
  NetUnblendedCost: "Net Unblended Cost",
  NetAmortizedCost: "Net Amortized Cost",
};

var METRIC_LABELS_JA = {
  UnblendedCost: "非ブレンドコスト",
  AmortizedCost: "償却コスト",
  BlendedCost: "ブレンドコスト",
  NetUnblendedCost: "非ブレンド純コスト",
  NetAmortizedCost: "償却純コスト",
};

// ---- Metric Help Tooltip ----
var METRIC_DESCRIPTIONS = {
  UnblendedCost: "実際の使用料金。各アカウントが実際に支払う金額で、リザーブドインスタンス（RI）やSavings Plansの割引が購入アカウントにのみ適用される。",
  AmortizedCost: "RIやSavings Plansの前払い費用を契約期間で均等に按分した料金。月ごとのコスト変動を抑え、長期的なコスト傾向の分析に適している。",
  BlendedCost: "組織内の全アカウントの平均料金率で計算したコスト。一括請求（Consolidated Billing）で、RI等の割引効果が全アカウントに均等に配分される。",
  NetUnblendedCost: "契約割引（EDP: Enterprise Discount Program等）適用後の実コスト。Unblended CostからAWS との個別契約による割引を差し引いた金額。",
  NetAmortizedCost: "契約割引適用後の按分コスト。Amortized CostからEDP等の割引を差し引いた金額で、最も「実態に近い」コストを示す。",
};

var activeTooltip = null;

function showMetricTooltip() {
  if (activeTooltip) { removeMetricTooltip(); return; }
  var tt = document.createElement("div");
  tt.className = "metric-tooltip";
  var h4 = document.createElement("h4");
  h4.textContent = "コストメトリクスの種類";
  tt.appendChild(h4);
  var dl = document.createElement("dl");
  Object.keys(METRIC_DESCRIPTIONS).forEach(function(key) {
    var dt = document.createElement("dt");
    dt.textContent = METRIC_LABELS[key];
    var dtJa = document.createElement("span");
    dtJa.className = "metric-dt-ja";
    dtJa.textContent = METRIC_LABELS_JA[key];
    dt.appendChild(dtJa);
    var dd = document.createElement("dd"); dd.textContent = METRIC_DESCRIPTIONS[key];
    dl.appendChild(dt); dl.appendChild(dd);
  });
  tt.appendChild(dl);
  document.body.appendChild(tt);

  var btnRect = metricHelpBtn.getBoundingClientRect();
  var ttRect = tt.getBoundingClientRect();
  var top = btnRect.bottom + 8;
  var left = btnRect.left - ttRect.width / 2 + btnRect.width / 2;
  if (left < 8) left = 8;
  if (left + ttRect.width > window.innerWidth - 8) left = window.innerWidth - ttRect.width - 8;
  if (top + ttRect.height > window.innerHeight - 8) top = btnRect.top - ttRect.height - 8;
  tt.style.top = top + "px";
  tt.style.left = left + "px";
  activeTooltip = tt;
}

function removeMetricTooltip() {
  if (activeTooltip) { activeTooltip.remove(); activeTooltip = null; }
}

metricHelpBtn.addEventListener("click", function(e) { e.stopPropagation(); showMetricTooltip(); });
document.addEventListener("click", function(e) { if (activeTooltip && !activeTooltip.contains(e.target) && e.target !== metricHelpBtn) removeMetricTooltip(); });

// Metric change re-renders with stored data
costMetricEl.addEventListener("change", function() {
  if (lastAccountResults) renderDashboard(lastAccountResults, lastGranularity);
});

// ============================================================
// Cost Explorer
// ============================================================
var costFetchBtn = document.getElementById("cost-fetch");
var costClearCacheBtn = document.getElementById("cost-clear-cache");
var costLoadingEl = document.getElementById("cost-loading");
var costLoadingTextEl = document.getElementById("cost-loading-text");
var costSummaryEl = document.getElementById("cost-summary");
var overviewWrapperEl = document.getElementById("overview-wrapper");
var accountChartsEl = document.getElementById("account-charts");
var costTableSectionEl = document.getElementById("cost-table-section");
var costTableHeadEl = document.getElementById("cost-table-head");
var costTableBodyEl = document.getElementById("cost-table-body");

var overviewChart = null;
var acctCharts = [];

var COLORS = [
  "#f0a030","#60a5fa","#34d399","#f87171","#a78bfa",
  "#fb923c","#38bdf8","#4ade80","#f472b6","#c084fc",
  "#fbbf24","#2dd4bf","#e879f9","#818cf8","#22d3ee",
  "#a3e635","#fb7185","#94a3b8","#fdba74","#86efac",
];
function getColor(i) { return COLORS[i % COLORS.length]; }
var CF = "#8b95a8", CG = "#2a2f3c", CFont = { family: "'JetBrains Mono', monospace", size: 10 };

// --- Custom HTML tooltip (aligned labels & values) ---
function getOrCreateTooltipEl(chart) {
  var container = chart.canvas.parentNode;
  var el = container.querySelector(".chart-tooltip");
  if (!el) {
    el = document.createElement("div");
    el.className = "chart-tooltip";
    container.appendChild(el);
  }
  return el;
}

function externalTooltipHandler(context) {
  var tooltip = context.tooltip;
  var el = getOrCreateTooltipEl(context.chart);
  if (tooltip.opacity === 0) { el.style.opacity = "0"; return; }

  while (el.firstChild) el.removeChild(el.firstChild);

  if (tooltip.title && tooltip.title.length) {
    var titleDiv = document.createElement("div");
    titleDiv.className = "chart-tooltip-title";
    titleDiv.textContent = tooltip.title[0];
    el.appendChild(titleDiv);
  }

  var body = tooltip.body || [];
  var table = document.createElement("div");
  table.className = "chart-tooltip-body";

  // Sort items by value descending
  var items = (tooltip.dataPoints || []).slice();
  items.sort(function(a, b) { return (b.parsed.y || 0) - (a.parsed.y || 0); });

  items.forEach(function(item) {
    if (item.parsed.y === 0 || item.parsed.y == null) return;
    var row = document.createElement("div");
    row.className = "chart-tooltip-row";

    var swatch = document.createElement("span");
    swatch.className = "chart-tooltip-swatch";
    var color = item.dataset.borderColor || item.dataset.backgroundColor;
    swatch.style.background = color;
    row.appendChild(swatch);

    var label = document.createElement("span");
    label.className = "chart-tooltip-label";
    label.textContent = item.dataset.label;
    row.appendChild(label);

    var value = document.createElement("span");
    value.className = "chart-tooltip-value";
    value.textContent = formatUSD(item.parsed.y);
    row.appendChild(value);

    table.appendChild(row);
  });

  el.appendChild(table);

  var pos = context.chart.canvas.getBoundingClientRect();
  el.style.opacity = "1";
  el.style.left = tooltip.caretX + "px";
  el.style.top = tooltip.caretY + "px";
}
function formatUSD(n) { return "$" + n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2}); }
function getAccountName(id) { for(var i=0;i<allAccounts.length;i++) if(allAccounts[i].accountId===id) return allAccounts[i].accountName; return id; }

// --- Fetch single account with client cache ---
async function fetchAccountCost(id, start, end, granularity) {
  var cacheKey = "cost:" + id + ":" + start + ":" + end + ":" + granularity;
  var cached = clientCacheGet(cacheKey);
  if (cached) {
    console.info("[awscc] client cache hit", { accountId: id, start: start, end: end, granularity: granularity });
    return cached;
  }

  var url = "/api/cost/" + id + "?start=" + start + "&end=" + end + "&granularity=" + granularity + "&group_by=SERVICE";
  var startedAt = performance.now();
  try {
    var res = await fetch(url);
    console.info("[awscc] account cost fetch", {
      accountId: id,
      start: start,
      end: end,
      granularity: granularity,
      status: res.status,
      elapsedMs: Math.round(performance.now() - startedAt),
    });
    if (!res.ok) return { accountId: id, accountName: getAccountName(id), results: [], error: "HTTP " + res.status };
    var data = await res.json();
    if (!data.accountName) data.accountName = getAccountName(data.accountId);
    clientCacheSet(cacheKey, data);
    return data;
  } catch (e) {
    return { accountId: id, accountName: getAccountName(id), results: [], error: "Request failed" };
  }
}

costFetchBtn.addEventListener("click", fetchCostData);

var CONCURRENCY = 6; // max parallel requests (avoid AWS throttling)

async function fetchCostData() {
  var range = getDateRange();
  var granularity = document.getElementById("cost-granularity").value;
  var targetIds = Array.from(selectedAccountIds);
  if (!targetIds.length) { showError("Please select at least one account"); return; }
  var fetchStartedAt = performance.now();

  costFetchBtn.disabled = true;
  costLoadingEl.classList.remove("hidden");
  var loadingBarFill = costLoadingEl.querySelector(".loading-bar-fill");
  loadingBarFill.style.animation = "none";
  loadingBarFill.style.width = "0%";
  loadingBarFill.style.transition = "width 0.3s ease";
  costLoadingTextEl.textContent = "Loading cost data for " + targetIds.length + " account(s)...";
  costSummaryEl.classList.add("hidden");
  overviewWrapperEl.classList.add("hidden");
  costTableSectionEl.classList.add("hidden");
  chartNavEl.classList.add("hidden");

  // Clear previous account charts for streaming
  acctCharts.forEach(function(c){ c.destroy(); });
  acctCharts = [];
  chartCanvasMap.clear();
  globalServiceColorMap = {};
  if (chartObserver) { chartObserver.disconnect(); chartObserver = null; }
  while (accountChartsEl.firstChild) accountChartsEl.removeChild(accountChartsEl.firstChild);
  accountChartsEl.classList.remove("hidden");

  try {
    var accountResults = [];
    var done = 0;
    var total = targetIds.length;

    // Concurrency-limited fetch with progress + streaming chart render
    var queue = targetIds.slice();
    var active = 0;

    await new Promise(function(resolve, reject) {
      function next() {
        if (done >= total) { resolve(); return; }
        while (active < CONCURRENCY && queue.length > 0) {
          active++;
          var id = queue.shift();
          fetchAccountCost(id, range.start, range.end, granularity).then(function(result) {
            accountResults.push(result);
            done++;
            active--;
            var pct = Math.round((done / total) * 100);
            loadingBarFill.style.width = pct + "%";
            costLoadingTextEl.textContent = "Loading... " + done + " / " + total + " accounts";
            // Stream: render this account's chart immediately
            appendAccountChart(result, granularity);
            next();
          }).catch(function(err) {
            done++;
            active--;
            next();
          });
        }
      }
      next();
    });
    var fetchElapsedMs = Math.round(performance.now() - fetchStartedAt);

    // Sort results to match original account order
    var idOrder = {};
    targetIds.forEach(function(id, i) { idOrder[id] = i; });
    accountResults.sort(function(a, b) { return (idOrder[a.accountId] || 0) - (idOrder[b.accountId] || 0); });

    lastAccountResults = accountResults;
    lastGranularity = granularity;
    // Render summary / overview / table (need all accounts), and re-sort account charts
    var renderStartedAt = performance.now();
    renderDashboard(accountResults, granularity);
    var renderElapsedMs = Math.round(performance.now() - renderStartedAt);
    console.info("[awscc] dashboard timing", {
      accounts: accountResults.length,
      granularity: granularity,
      fetchElapsedMs: fetchElapsedMs,
      renderElapsedMs: renderElapsedMs,
      totalElapsedMs: Math.round(performance.now() - fetchStartedAt),
    });
    setStatus("Cost data loaded (" + accountResults.length + " accounts)", "ok");
  } catch (e) {
    showError("Failed: " + e.message);
  } finally {
    costFetchBtn.disabled = false;
    costLoadingEl.classList.add("hidden");
    // Restore animated loading bar for future use
    var fill = costLoadingEl.querySelector(".loading-bar-fill");
    fill.style.animation = "";
    fill.style.width = "";
    fill.style.transition = "";
  }
}

costClearCacheBtn.addEventListener("click", async function() {
  var clientCount = clientCacheClear();
  var res = await fetch("/api/cache", { method: "DELETE" });
  var data = await res.json();
  setStatus("Cache cleared (server: " + data.deleted + ", client: " + clientCount + ")", "ok");
});

// ============================================================
// Render Dashboard
// ============================================================
function renderDashboard(accountResults, granularity) {
  var selectedMetric = costMetricEl.value;
  // --- Aggregate ---
  var periodsSet = {};
  var acctAgg = []; // { name, id, total, error, svcByPeriod: { svc: { period: cost } } }

  accountResults.forEach(function(ar) {
    var name = ar.accountName || ar.accountId;
    var svcByPeriod = {};
    var total = 0;

    ar.results.forEach(function(period) {
      var pk = period.TimePeriod.Start;
      periodsSet[pk] = true;
      (period.Groups || []).forEach(function(g) {
        var svc = g.Keys[0];
        // Use selected metric, fall back to UnblendedCost if unavailable
        var metrics = g.Metrics || {};
        var m = metrics[selectedMetric] || metrics.UnblendedCost;
        var cost = m ? parseFloat(m.Amount || 0) : 0;
        svcByPeriod[svc] = svcByPeriod[svc] || {};
        svcByPeriod[svc][pk] = (svcByPeriod[svc][pk] || 0) + cost;
        total += cost;
      });
    });

    acctAgg.push({ name: name, id: ar.accountId, total: total, error: ar.error, svcByPeriod: svcByPeriod });
  });

  var periods = Object.keys(periodsSet).sort();
  acctAgg.sort(function(a,b){ return b.total - a.total; });

  var globalSvcTotals = {};
  acctAgg.forEach(function(acct) {
    Object.keys(acct.svcByPeriod).forEach(function(svc) {
      var sum = 0;
      periods.forEach(function(p) { sum += (acct.svcByPeriod[svc][p] || 0); });
      globalSvcTotals[svc] = (globalSvcTotals[svc] || 0) + sum;
    });
  });
  var sortedSvcs = Object.keys(globalSvcTotals).sort(function(a, b) {
    return globalSvcTotals[b] - globalSvcTotals[a];
  });
  globalServiceColorMap = {};
  sortedSvcs.forEach(function(svc, idx) {
    globalServiceColorMap[svc] = getColor(idx);
  });

  renderSummary(acctAgg);
  renderOverviewChart(acctAgg, periods, granularity);
  renderAccountCharts(acctAgg, periods, granularity);
  renderCostTable(acctAgg);
}

// --- Summary ---
function renderSummary(acctAgg) {
  while (costSummaryEl.firstChild) costSummaryEl.removeChild(costSummaryEl.firstChild);
  var grandTotal = acctAgg.reduce(function(s,a){ return s+a.total; }, 0);
  var top = acctAgg.length > 0 ? acctAgg[0] : null;
  [
    { label: "Total Cost", value: formatUSD(grandTotal) },
    { label: "Accounts", value: String(acctAgg.length), sub: acctAgg.filter(function(a){return a.total>0;}).length + " with cost" },
    { label: "Top Account", value: top ? top.name : "\u2014", sub: top ? formatUSD(top.total) : "" },
    { label: "Errors", value: String(acctAgg.filter(function(a){return a.error;}).length), sub: "failed to fetch" },
  ].forEach(function(c) {
    var card = document.createElement("div"); card.className = "summary-card";
    var l = document.createElement("div"); l.className="label"; l.textContent=c.label; card.appendChild(l);
    var v = document.createElement("div"); v.className="value"; v.textContent=c.value; card.appendChild(v);
    if (c.sub) { var s = document.createElement("div"); s.className="sub"; s.textContent=c.sub; card.appendChild(s); }
    costSummaryEl.appendChild(card);
  });
  costSummaryEl.classList.remove("hidden");
}

// --- Overview: line chart, one line per account (total cost) ---
function renderOverviewChart(acctAgg, periods, granularity) {
  if (!periods.length) { overviewWrapperEl.classList.add("hidden"); return; }
  var labels = periods.map(function(p){ return granularity==="DAILY" ? p : p.substring(0,7); });

  // Show top 15 accounts as lines, rest as "Others"
  var top = acctAgg.slice(0, 15);
  var others = acctAgg.slice(15);

  var datasets = top.map(function(acct, idx) {
    // Sum all services per period for this account
    return {
      label: acct.name,
      data: periods.map(function(p) {
        var sum = 0;
        Object.keys(acct.svcByPeriod).forEach(function(svc) { sum += (acct.svcByPeriod[svc][p] || 0); });
        return sum;
      }),
      borderColor: getColor(idx),
      backgroundColor: getColor(idx) + "18",
      borderWidth: 2,
      pointRadius: 3,
      pointHoverRadius: 6,
      tension: 0.25,
      fill: false,
    };
  });

  if (others.length) {
    datasets.push({
      label: "Others (" + others.length + ")",
      data: periods.map(function(p) {
        var sum = 0;
        others.forEach(function(acct) {
          Object.keys(acct.svcByPeriod).forEach(function(svc) { sum += (acct.svcByPeriod[svc][p] || 0); });
        });
        return sum;
      }),
      borderColor: "#3a3f4c",
      borderWidth: 2,
      borderDash: [5,3],
      pointRadius: 2,
      tension: 0.25,
      fill: false,
    });
  }

  if (overviewChart) overviewChart.destroy();
  overviewChart = new Chart(document.getElementById("overview-chart").getContext("2d"), {
    type: "line",
    data: { labels: labels, datasets: datasets },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { color: CF, boxWidth: 10, padding: 10, font: CFont } },
        tooltip: { enabled: false, external: externalTooltipHandler },
      },
      scales: {
        x: { ticks: { color: CF, font: CFont }, grid: { color: CG } },
        y: { ticks: { color: CF, font: CFont, callback: function(v){ return "$"+v.toLocaleString(); } }, grid: { color: CG } },
      },
    },
  });
  overviewWrapperEl.classList.remove("hidden");
}

// --- Per-account charts: stacked bar by service (lazy via IntersectionObserver) ---
var chartObserver = null;
var chartCanvasMap = new Map(); // canvas -> chartData (shared across streaming & full render)

function ensureChartObserver() {
  if (chartObserver) return;
  chartObserver = new IntersectionObserver(function(entries) {
    entries.forEach(function(ioEntry) {
      if (!ioEntry.isIntersecting) return;
      var canvas = ioEntry.target;
      var data = chartCanvasMap.get(canvas);
      if (!data) return;
      initChartOnCanvas(canvas, data);
    });
  }, { rootMargin: "200px" });
}

function initChartOnCanvas(canvas, data) {
  var chart = new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: { labels: data.labels, datasets: data.datasets },
    options: {
      responsive: true,
      animation: { duration: 400 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { color: CF, boxWidth: 10, padding: 8, font: CFont } },
        tooltip: { enabled: false, external: externalTooltipHandler },
      },
      scales: {
        x: { stacked: true, ticks: { color: CF, font: CFont }, grid: { display: false } },
        y: { stacked: true, ticks: { color: CF, font: CFont, callback: function(v){ return "$"+v.toLocaleString(); } }, grid: { color: CG } },
      },
    },
  });
  acctCharts.push(chart);
  chartCanvasMap.delete(canvas);
  if (chartObserver) chartObserver.unobserve(canvas);
}

function aggregateOneAccount(ar, selectedMetric) {
  var name = ar.accountName || ar.accountId;
  var svcByPeriod = {};
  var total = 0;
  var periodsSet = {};
  ar.results.forEach(function(period) {
    var pk = period.TimePeriod.Start;
    periodsSet[pk] = true;
    (period.Groups || []).forEach(function(g) {
      var svc = g.Keys[0];
      var metrics = g.Metrics || {};
      var m = metrics[selectedMetric] || metrics.UnblendedCost;
      var cost = m ? parseFloat(m.Amount || 0) : 0;
      svcByPeriod[svc] = svcByPeriod[svc] || {};
      svcByPeriod[svc][pk] = (svcByPeriod[svc][pk] || 0) + cost;
      total += cost;
    });
  });
  return { name: name, id: ar.accountId, total: total, error: ar.error, svcByPeriod: svcByPeriod, periods: Object.keys(periodsSet).sort() };
}

var TOP_SERVICE_COUNT = 12;
var expandedCharts = new Set();
var globalServiceColorMap = {};

function buildChartDatasets(acct, periods, showAll) {
  var svcs = Object.keys(acct.svcByPeriod);
  svcs.sort(function(a, b) {
    var ta = 0, tb = 0;
    periods.forEach(function(p) { ta += (acct.svcByPeriod[a][p] || 0); tb += (acct.svcByPeriod[b][p] || 0); });
    return tb - ta;
  });
  var limit = showAll ? svcs.length : TOP_SERVICE_COUNT;
  var topSvcs = svcs.slice(0, limit);
  var otherSvcs = svcs.slice(limit);
  var datasets = topSvcs.map(function(svc) {
    return {
      label: svc,
      data: periods.map(function(p) { return acct.svcByPeriod[svc][p] || 0; }),
      backgroundColor: globalServiceColorMap[svc] || getColor(Object.keys(globalServiceColorMap).length),
      borderRadius: 2,
    };
  });
  if (otherSvcs.length) {
    datasets.push({
      label: "Others (" + otherSvcs.length + ")",
      data: periods.map(function(p) {
        var sum = 0; otherSvcs.forEach(function(s) { sum += (acct.svcByPeriod[s][p] || 0); }); return sum;
      }),
      backgroundColor: "#3a3f4c",
      borderRadius: 2,
    });
  }
  return { datasets: datasets, totalSvcs: svcs.length };
}

function rebuildChartCard(card, acct, periods, granularity, showAll) {
  var canvas = card.querySelector("canvas");
  var existingChart = acctCharts.find(function(c) { return c.canvas === canvas; });
  if (existingChart) {
    acctCharts = acctCharts.filter(function(c) { return c !== existingChart; });
    existingChart.destroy();
  }
  chartCanvasMap.delete(canvas);
  if (chartObserver) chartObserver.unobserve(canvas);

  var labels = periods.map(function(p) { return granularity === "DAILY" ? p : p.substring(0, 7); });
  var built = buildChartDatasets(acct, periods, showAll);
  var chartData = { labels: labels, datasets: built.datasets };

  ensureChartObserver();
  chartCanvasMap.set(canvas, chartData);
  chartObserver.observe(canvas);
}

function buildAccountChartCard(acct, periods, granularity) {
  var labels = periods.map(function(p) { return granularity === "DAILY" ? p : p.substring(0, 7); });
  var showAll = expandedCharts.has(acct.id);
  var built = buildChartDatasets(acct, periods, showAll);

  var card = document.createElement("div"); card.className = "account-chart-card";
  card.id = "chart-" + acct.id;
  var header = document.createElement("div"); header.className = "chart-header";
  var h3 = document.createElement("h3"); h3.textContent = acct.name;
  var idSpan = document.createElement("span"); idSpan.className = "acct-id"; idSpan.textContent = acct.id;
  h3.appendChild(idSpan);
  header.appendChild(h3);

  var svcBtnWrap = document.createElement("div"); svcBtnWrap.className = "svc-resource-buttons";
  var costServiceNames = Object.keys(acct.svcByPeriod);
  costServiceNames.forEach(function(costSvcName) {
    var info = RESOURCE_CAPABLE_SERVICES[costSvcName];
    if (!info) return;
    var svcBtn = document.createElement("button");
    svcBtn.type = "button";
    svcBtn.className = "svc-resource-btn";
    svcBtn.textContent = info.label;
    svcBtn.title = "View " + info.label + " resources";
    svcBtn.addEventListener("click", function() { openResourceDrawer(acct.id, info.key, acct.name); });
    svcBtnWrap.appendChild(svcBtn);
  });
  if (svcBtnWrap.children.length) header.appendChild(svcBtnWrap);

  var totalWrap = document.createElement("div"); totalWrap.className = "acct-total-wrap";
  if (built.totalSvcs > TOP_SERVICE_COUNT) {
    var toggle = document.createElement("span");
    toggle.className = "svc-toggle";
    var btnTop = document.createElement("button");
    btnTop.type = "button";
    btnTop.textContent = "Top " + TOP_SERVICE_COUNT;
    var btnAll = document.createElement("button");
    btnAll.type = "button";
    btnAll.textContent = "All " + built.totalSvcs;
    function updateToggleState(expanded) {
      btnTop.className = "svc-toggle-btn" + (expanded ? "" : " active");
      btnAll.className = "svc-toggle-btn" + (expanded ? " active" : "");
    }
    updateToggleState(showAll);
    btnTop.addEventListener("click", function() {
      if (!expandedCharts.has(acct.id)) return;
      expandedCharts.delete(acct.id);
      updateToggleState(false);
      rebuildChartCard(card, acct, periods, granularity, false);
    });
    btnAll.addEventListener("click", function() {
      if (expandedCharts.has(acct.id)) return;
      expandedCharts.add(acct.id);
      updateToggleState(true);
      rebuildChartCard(card, acct, periods, granularity, true);
    });
    toggle.appendChild(btnTop);
    toggle.appendChild(btnAll);
    totalWrap.appendChild(toggle);
  }
  var totalLabel = document.createElement("span"); totalLabel.className = "acct-total-label";
  var metricName = METRIC_LABELS[costMetricEl.value] || costMetricEl.value;
  var periodRange = periods.length ? " (" + labels[0] + " \u2013 " + labels[labels.length - 1] + ")" : "";
  totalLabel.textContent = metricName + periodRange;
  totalWrap.appendChild(totalLabel);
  var totalSpan = document.createElement("span"); totalSpan.className = "acct-total"; totalSpan.textContent = formatUSD(acct.total);
  totalWrap.appendChild(totalSpan);
  header.appendChild(totalWrap);
  card.appendChild(header);
  var canvas = document.createElement("canvas");
  card.appendChild(canvas);

  return { card: card, canvas: canvas, chartData: { labels: labels, datasets: built.datasets } };
}

// Streaming: append one account chart card as data arrives
function appendAccountChart(ar, granularity) {
  var selectedMetric = costMetricEl.value;
  var acct = aggregateOneAccount(ar, selectedMetric);
  if (acct.total <= 0) return;
  var periods = acct.periods;
  if (!periods.length) return;

  Object.keys(acct.svcByPeriod).forEach(function(svc) {
    if (!globalServiceColorMap[svc]) {
      globalServiceColorMap[svc] = getColor(Object.keys(globalServiceColorMap).length);
    }
  });

  var entry = buildAccountChartCard(acct, periods, granularity);
  accountChartsEl.appendChild(entry.card);
  accountChartsEl.classList.remove("hidden");

  ensureChartObserver();
  chartCanvasMap.set(entry.canvas, entry.chartData);
  chartObserver.observe(entry.canvas);
}

// Full re-render (for metric change / final sort)
function renderAccountCharts(acctAgg, periods, granularity) {
  acctCharts.forEach(function(c){ c.destroy(); });
  acctCharts = [];
  chartCanvasMap.clear();
  if (chartObserver) { chartObserver.disconnect(); chartObserver = null; }
  while (accountChartsEl.firstChild) accountChartsEl.removeChild(accountChartsEl.firstChild);

  if (!periods.length) { accountChartsEl.classList.add("hidden"); chartNavEl.classList.add("hidden"); return; }
  var withCost = acctAgg.filter(function(a){ return a.total > 0; });

  ensureChartObserver();
  withCost.forEach(function(acct) {
    var entry = buildAccountChartCard(acct, periods, granularity);
    accountChartsEl.appendChild(entry.card);
    chartCanvasMap.set(entry.canvas, entry.chartData);
    chartObserver.observe(entry.canvas);
  });

  accountChartsEl.classList.remove("hidden");
  renderChartNav(withCost);
}

// --- Chart navigation ---
var chartNavEl = document.getElementById("chart-nav");
var chartNavListEl = document.getElementById("chart-nav-list");
var chartNavSearchEl = document.getElementById("chart-nav-search");

function renderChartNav(withCost) {
  while (chartNavListEl.firstChild) chartNavListEl.removeChild(chartNavListEl.firstChild);
  chartNavSearchEl.value = "";

  withCost.forEach(function(acct) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chart-nav-item";
    btn.dataset.searchText = (acct.name + " " + acct.id).toLowerCase();

    var nameSpan = document.createElement("span");
    nameSpan.textContent = acct.name;
    btn.appendChild(nameSpan);

    var costSpan = document.createElement("span");
    costSpan.className = "nav-cost";
    costSpan.textContent = formatUSD(acct.total);
    btn.appendChild(costSpan);

    btn.addEventListener("click", function() {
      var target = document.getElementById("chart-" + acct.id);
      if (!target) return;
      var navH = chartNavEl.offsetHeight || 0;
      var gap = 12;
      var y = target.getBoundingClientRect().top + window.scrollY - navH - gap;
      window.scrollTo({ top: Math.max(0, y), behavior: "smooth" });
    });

    chartNavListEl.appendChild(btn);
  });

  chartNavEl.classList.remove("hidden");
}

chartNavSearchEl.addEventListener("input", function() {
  var q = chartNavSearchEl.value.toLowerCase();
  chartNavListEl.querySelectorAll(".chart-nav-item").forEach(function(btn) {
    btn.style.display = btn.dataset.searchText.includes(q) ? "" : "none";
  });
});

// --- Cost table ---
function renderCostTable(acctAgg) {
  while (costTableHeadEl.firstChild) costTableHeadEl.removeChild(costTableHeadEl.firstChild);
  while (costTableBodyEl.firstChild) costTableBodyEl.removeChild(costTableBodyEl.firstChild);
  var headTr = document.createElement("tr");
  ["#","Account","Account ID","Cost (USD)","Share"].forEach(function(t){
    var th = document.createElement("th"); th.textContent=t;
    if(t==="Cost (USD)"||t==="Share") th.style.textAlign="right";
    headTr.appendChild(th);
  });
  costTableHeadEl.appendChild(headTr);
  var grandTotal = acctAgg.reduce(function(s,a){return s+a.total;},0);
  acctAgg.forEach(function(a,i){
    var tr = document.createElement("tr");
    tr.appendChild(createCell(String(i+1)));
    tr.appendChild(createCell(a.name,"account-name"));
    tr.appendChild(createCell(a.id,"account-id"));
    tr.appendChild(createCell(formatUSD(a.total),"cost-value"));
    tr.appendChild(createCell(grandTotal>0?((a.total/grandTotal)*100).toFixed(1)+"%":"\u2014","cost-value"));
    if(a.error) tr.style.opacity="0.4";
    costTableBodyEl.appendChild(tr);
  });
  costTableSectionEl.classList.remove("hidden");
}

// ============================================================
// Config Tab — Default Account Selection
// ============================================================
var CONFIG_STORAGE_KEY = "awscc:config:defaultAccounts";
var configAccountList = document.getElementById("config-account-list");
var configSearch = document.getElementById("config-account-search");
var configCountEl = document.getElementById("config-selected-count");
var configSelectedIds = new Set();
var serverDefaultAccountIds = undefined;

function loadDefaultAccountConfig() {
  if (serverDefaultAccountIds !== undefined) return serverDefaultAccountIds;
  try {
    var raw = localStorage.getItem(CONFIG_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) { /* ignore */ }
  return null;
}

function saveDefaultAccountConfig(ids) {
  localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(ids));
}

async function loadServerDefaultAccountConfig() {
  try {
    var res = await fetch("/api/config/default-accounts");
    if (!res.ok) return;
    var data = await res.json();
    serverDefaultAccountIds = data.accountIds || null;
    if (serverDefaultAccountIds === null) {
      var localSaved = loadDefaultAccountConfigFromLocalStorage();
      if (localSaved) {
        await saveServerDefaultAccountConfig(localSaved);
        serverDefaultAccountIds = localSaved;
      }
    }
  } catch (e) { /* keep localStorage fallback */ }
}

function loadDefaultAccountConfigFromLocalStorage() {
  try {
    var raw = localStorage.getItem(CONFIG_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) { /* ignore */ }
  return null;
}

async function saveServerDefaultAccountConfig(ids) {
  var res = await fetch("/api/config/default-accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accountIds: ids }),
  });
  if (!res.ok) throw new Error("Failed to save server config");
  serverDefaultAccountIds = ids;
}

async function clearServerDefaultAccountConfig() {
  var res = await fetch("/api/config/default-accounts", { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to clear server config");
  serverDefaultAccountIds = null;
}

function populateConfigAccountList() {
  while (configAccountList.firstChild) configAccountList.removeChild(configAccountList.firstChild);
  configSelectedIds.clear();
  var saved = loadDefaultAccountConfig();

  allAccounts.forEach(function(a) {
    var lbl = document.createElement("label");
    lbl.className = "config-account-item";
    lbl.dataset.searchText = (a.accountName + " " + a.accountId + " " + a.emailAddress).toLowerCase();

    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = a.accountId;
    cb.checked = saved ? saved.indexOf(a.accountId) !== -1 : true;
    lbl.appendChild(cb);

    var nameSpan = document.createElement("span");
    nameSpan.textContent = a.accountName;
    lbl.appendChild(nameSpan);

    var idSpan = document.createElement("span");
    idSpan.className = "config-acct-id";
    idSpan.textContent = a.accountId;
    lbl.appendChild(idSpan);

    configAccountList.appendChild(lbl);

    if (cb.checked) configSelectedIds.add(a.accountId);
  });

  updateConfigCount();
}

function updateConfigCount() {
  var total = allAccounts.length;
  var selected = configSelectedIds.size;
  if (selected === total) configCountEl.textContent = "All " + total + " accounts selected";
  else configCountEl.textContent = selected + " / " + total + " accounts selected";
}

function applyDefaultAccountSelection() {
  var saved = loadDefaultAccountConfig();
  if (!saved) return; // null = all accounts (default)
  selectedAccountIds = new Set(saved);
  // Update multi-select checkboxes
  msOptions.querySelectorAll("input[type=checkbox]").forEach(function(cb) {
    cb.checked = selectedAccountIds.has(cb.value);
  });
  updateToggleLabel();
}

configAccountList.addEventListener("change", function(e) {
  if (e.target.type !== "checkbox") return;
  if (e.target.checked) configSelectedIds.add(e.target.value);
  else configSelectedIds.delete(e.target.value);
  updateConfigCount();
});

document.getElementById("config-select-all").addEventListener("click", function() {
  configAccountList.querySelectorAll("input[type=checkbox]").forEach(function(cb) { cb.checked = true; });
  configSelectedIds = new Set(allAccounts.map(function(a) { return a.accountId; }));
  updateConfigCount();
});

document.getElementById("config-deselect-all").addEventListener("click", function() {
  configAccountList.querySelectorAll("input[type=checkbox]").forEach(function(cb) { cb.checked = false; });
  configSelectedIds.clear();
  updateConfigCount();
});

configSearch.addEventListener("input", function() {
  var q = configSearch.value.toLowerCase();
  configAccountList.querySelectorAll(".config-account-item").forEach(function(item) {
    item.style.display = item.dataset.searchText.includes(q) ? "" : "none";
  });
});

document.getElementById("config-save").addEventListener("click", async function() {
  var ids = Array.from(configSelectedIds);
  var syncFailed = false;
  if (ids.length === allAccounts.length) {
    localStorage.removeItem(CONFIG_STORAGE_KEY); // all = no config needed
    try { await clearServerDefaultAccountConfig(); } catch (e) { syncFailed = true; }
  } else {
    saveDefaultAccountConfig(ids);
    try { await saveServerDefaultAccountConfig(ids); } catch (e) { syncFailed = true; }
  }
  // Apply to current session's multi-select
  selectedAccountIds = new Set(ids.length ? ids : allAccounts.map(function(a) { return a.accountId; }));
  msOptions.querySelectorAll("input[type=checkbox]").forEach(function(cb) {
    cb.checked = selectedAccountIds.has(cb.value);
  });
  updateToggleLabel();
  showToast(syncFailed ? "Saved locally; server sync failed" : "Default accounts saved");
});

document.getElementById("config-reset").addEventListener("click", async function() {
  localStorage.removeItem(CONFIG_STORAGE_KEY);
  var syncFailed = false;
  try { await clearServerDefaultAccountConfig(); } catch (e) { syncFailed = true; }
  configAccountList.querySelectorAll("input[type=checkbox]").forEach(function(cb) { cb.checked = true; });
  configSelectedIds = new Set(allAccounts.map(function(a) { return a.accountId; }));
  updateConfigCount();
  // Reset multi-select too
  selectedAccountIds = new Set(allAccounts.map(function(a) { return a.accountId; }));
  msOptions.querySelectorAll("input[type=checkbox]").forEach(function(cb) { cb.checked = true; });
  updateToggleLabel();
  showToast(syncFailed ? "Reset locally; server sync failed" : "Reset to all accounts");
});

function showToast(msg) {
  var existing = document.querySelector(".config-saved-toast");
  if (existing) existing.remove();
  var toast = document.createElement("div");
  toast.className = "config-saved-toast";
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(function() { if (toast.parentNode) toast.remove(); }, 2200);
}

// ============================================================
// Back to Top
// ============================================================
var backToTopBtn = document.getElementById("back-to-top");

window.addEventListener("scroll", function() {
  if (window.scrollY > 400) backToTopBtn.classList.add("visible");
  else backToTopBtn.classList.remove("visible");
});

backToTopBtn.addEventListener("click", function() {
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// ============================================================
// Resource Drawer
// ============================================================
var RESOURCE_CAPABLE_SERVICES = {
  "Amazon Elastic Compute Cloud - Compute": { key: "ec2", label: "EC2" },
  "Amazon Elastic Container Service": { key: "ecs", label: "ECS" },
  "Amazon Relational Database Service": { key: "rds", label: "RDS" },
  "Amazon Simple Storage Service": { key: "s3", label: "S3" },
  "Amazon ElastiCache": { key: "elasticache", label: "Cache" },
};

var drawerEl = document.getElementById("resource-drawer");
var drawerOverlayEl = document.getElementById("drawer-overlay");
var drawerBodyEl = document.getElementById("drawer-body");
var drawerTitleEl = document.getElementById("drawer-title-text");
var drawerSubtitleEl = document.getElementById("drawer-subtitle");

var PRICING_RULES = {
  ec2: [
    "インスタンス時間課金（秒単位、最低60秒）",
    "On-Demand はインスタンスタイプ × リージョン × OS で決定",
    "RI / Savings Plans / Spot 割引は Actual (14d) に反映される",
    "EBS ストレージ・データ転送・Elastic IP は別料金",
  ],
  ecs: [
    "Fargate: vCPU 秒 + メモリ GB 秒の従量課金",
    "EC2 起動タイプ: 基盤の EC2 インスタンス料金が課金される",
    "タスク定義の vCPU / メモリ設定がコストに直結",
  ],
  rds: [
    "インスタンス時間課金（秒単位、最低10分）",
    "On-Demand はインスタンスクラス × エンジン × リージョンで決定",
    "Multi-AZ はシングル AZ の約2倍",
    "ストレージ (GB-月)・IOPS・バックアップ・データ転送は別料金",
    "Aurora は ACU（Aurora Capacity Unit）ベースの課金もある",
  ],
  s3: [
    "ストレージ (GB-月) + リクエスト数 + データ転送で課金",
    "ストレージクラスで単価が異なる (Standard / IA / Glacier 等)",
    "インスタンス単価の概念がないため On-Demand 列なし",
  ],
  elasticache: [
    "ノード時間課金（秒単位）",
    "On-Demand はノードタイプ × エンジン × リージョンで決定",
    "Serverless は ECPU + ストレージ GB の従量課金",
    "データ転送・バックアップは別料金",
  ],
};

function openResourceDrawer(accountId, serviceKey, accountName) {
  var labelMap = {};
  Object.keys(RESOURCE_CAPABLE_SERVICES).forEach(function(k) {
    var s = RESOURCE_CAPABLE_SERVICES[k];
    labelMap[s.key] = s.label;
  });
  drawerTitleEl.textContent = (labelMap[serviceKey] || serviceKey) + " Resources";
  drawerSubtitleEl.textContent = accountName + " (" + accountId + ")";
  activeDrawerService = serviceKey;
  currentCostUnit = "/h";

  while (drawerBodyEl.firstChild) drawerBodyEl.removeChild(drawerBodyEl.firstChild);
  var loadingDiv = document.createElement("div");
  loadingDiv.className = "drawer-loading";
  loadingDiv.textContent = "Loading resources...";
  drawerBodyEl.appendChild(loadingDiv);

  drawerOverlayEl.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  requestAnimationFrame(function() {
    drawerOverlayEl.classList.add("visible");
    drawerEl.classList.add("open");
  });

  fetch("/api/resources/" + accountId + "?service=" + serviceKey)
    .then(function(res) { return res.json(); })
    .then(function(data) {
      while (drawerBodyEl.firstChild) drawerBodyEl.removeChild(drawerBodyEl.firstChild);
      var svcData = data.services && data.services[serviceKey];
      if (!svcData || !svcData.resources || svcData.resources.length === 0) {
        var empty = document.createElement("div");
        empty.className = "drawer-empty";
        empty.textContent = "No " + (labelMap[serviceKey] || serviceKey) + " resources found.";
        drawerBodyEl.appendChild(empty);
        return;
      }
      renderResourceTable(serviceKey, svcData.resources);
    })
    .catch(function(err) {
      while (drawerBodyEl.firstChild) drawerBodyEl.removeChild(drawerBodyEl.firstChild);
      var errDiv = document.createElement("div");
      errDiv.className = "drawer-empty";
      errDiv.textContent = "Failed to load: " + err.message;
      drawerBodyEl.appendChild(errDiv);
    });
}

function closeResourceDrawer() {
  drawerEl.classList.remove("open");
  drawerOverlayEl.classList.remove("visible");
  document.body.style.overflow = "";
  setTimeout(function() { drawerOverlayEl.classList.add("hidden"); }, 300);
}

document.getElementById("drawer-close").addEventListener("click", closeResourceDrawer);
drawerOverlayEl.addEventListener("click", closeResourceDrawer);
document.addEventListener("keydown", function(e) {
  if (e.key === "Escape" && drawerEl.classList.contains("open")) closeResourceDrawer();
});

var drawerHelpBtn = document.getElementById("drawer-help-btn");
var activeDrawerService = null;

var currentCostUnit = "/h";
var COST_UNITS = ["/h", "/d", "/m"];
var COST_UNIT_MULTIPLIERS = {
  ondemand: { "/h": 1, "/d": 24, "/m": 720 },
  actual: { "/h": 1 / 336, "/d": 1 / 14, "/m": 30 / 14 },
};

function cycleCostUnit() {
  var idx = COST_UNITS.indexOf(currentCostUnit);
  currentCostUnit = COST_UNITS[(idx + 1) % COST_UNITS.length];
  drawerBodyEl.querySelectorAll("td[data-cost-type]").forEach(function(td) {
    var raw = parseFloat(td.dataset.rawValue);
    var costType = td.dataset.costType;
    if (isNaN(raw) || raw <= 0) return;
    var converted = raw * (COST_UNIT_MULTIPLIERS[costType][currentCostUnit] || 1);
    td.textContent = "$" + converted.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + currentCostUnit;
  });
  drawerBodyEl.querySelectorAll("th[data-cost-column]").forEach(function(th) {
    th.textContent = th.dataset.costLabel + " " + currentCostUnit;
  });
}

drawerHelpBtn.addEventListener("click", function() {
  var existing = drawerBodyEl.querySelector(".drawer-pricing-rules");
  if (existing) { existing.remove(); return; }
  var rules = PRICING_RULES[activeDrawerService];
  if (!rules) return;
  var panel = document.createElement("div");
  panel.className = "drawer-pricing-rules";
  var labelMap = {};
  Object.keys(RESOURCE_CAPABLE_SERVICES).forEach(function(k) {
    var s = RESOURCE_CAPABLE_SERVICES[k]; labelMap[s.key] = s.label;
  });
  var h4 = document.createElement("h4");
  h4.textContent = (labelMap[activeDrawerService] || activeDrawerService) + " の課金ルール";
  panel.appendChild(h4);
  var ul = document.createElement("ul");
  rules.forEach(function(rule) {
    var li = document.createElement("li");
    li.textContent = rule;
    ul.appendChild(li);
  });
  panel.appendChild(ul);
  drawerBodyEl.insertBefore(panel, drawerBodyEl.firstChild);
});

var RESOURCE_TABLE_COLUMNS = {
  ec2: [
    { key: "name", label: "Name" },
    { key: "instanceId", label: "Instance ID" },
    { key: "instanceType", label: "Type" },
    { key: "state", label: "State", isState: true },
    { key: "onDemandPrice", label: "On-Demand", isCost: true, unit: "/h" },
    { key: "actualCost", label: "Actual (14d)", isCost: true },
    { key: "region", label: "Region" },
  ],
  ecs: [
    { key: "clusterName", label: "Cluster" },
    { key: "serviceName", label: "Service" },
    { key: "runningCount", label: "Running", isNum: true },
    { key: "desiredCount", label: "Desired", isNum: true },
    { key: "launchType", label: "Launch" },
    { key: "actualCost", label: "Actual (14d)", isCost: true },
    { key: "region", label: "Region" },
  ],
  rds: [
    { key: "dbInstanceId", label: "DB Instance" },
    { key: "engine", label: "Engine" },
    { key: "instanceClass", label: "Class" },
    { key: "status", label: "Status", isState: true },
    { key: "onDemandPrice", label: "On-Demand", isCost: true, unit: "/h" },
    { key: "actualCost", label: "Actual (14d)", isCost: true },
    { key: "region", label: "Region" },
  ],
  s3: [
    { key: "bucketName", label: "Bucket" },
    { key: "region", label: "Region" },
    { key: "actualCost", label: "Actual (14d)", isCost: true },
    { key: "creationDate", label: "Created" },
  ],
  elasticache: [
    { key: "clusterId", label: "Cluster ID" },
    { key: "engine", label: "Engine" },
    { key: "nodeType", label: "Node Type" },
    { key: "numNodes", label: "Nodes", isNum: true },
    { key: "status", label: "Status", isState: true },
    { key: "onDemandPrice", label: "On-Demand", isCost: true, unit: "/h" },
    { key: "actualCost", label: "Actual (14d)", isCost: true },
    { key: "region", label: "Region" },
  ],
};

function getStateDotClass(value) {
  var v = String(value).toLowerCase();
  if (v === "running" || v === "available" || v === "active") return "running";
  if (v === "stopped" || v === "terminated" || v === "deleted") return "stopped";
  return "other";
}

function renderResourceTable(serviceKey, resources) {
  var columns = RESOURCE_TABLE_COLUMNS[serviceKey];
  if (!columns) return;
  var visibleCols = columns.filter(function(c) { return c.key !== "region"; });

  var byRegion = {};
  resources.forEach(function(r) {
    var region = r.region || "global";
    if (!byRegion[region]) byRegion[region] = [];
    byRegion[region].push(r);
  });
  var regionKeys = Object.keys(byRegion).sort();

  var table = document.createElement("table");
  table.className = "resource-table";

  var thead = document.createElement("thead");
  var headerRow = document.createElement("tr");
  visibleCols.forEach(function(col) {
    var th = document.createElement("th");
    if (col.isCost) {
      th.textContent = col.label + " " + currentCostUnit;
      th.style.textAlign = "right";
      th.style.cursor = "pointer";
      th.dataset.costColumn = "true";
      th.dataset.costLabel = col.label;
      th.addEventListener("click", cycleCostUnit);
    } else {
      th.textContent = col.label;
    }
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  regionKeys.forEach(function(region) {
    var items = byRegion[region];
    var tbody = document.createElement("tbody");

    var regionRow = document.createElement("tr");
    regionRow.className = "region-separator";
    var regionTd = document.createElement("td");
    regionTd.colSpan = visibleCols.length;
    regionTd.textContent = region + " \u2014 " + items.length + " resource" + (items.length !== 1 ? "s" : "");
    regionRow.appendChild(regionTd);
    tbody.appendChild(regionRow);

    items.forEach(function(item) {
      var tr = document.createElement("tr");
      visibleCols.forEach(function(col) {
        var td = document.createElement("td");
        var val = item[col.key];
        if (col.isState) {
          var stateWrap = document.createElement("span");
          stateWrap.className = "resource-state";
          var dot = document.createElement("span");
          dot.className = "resource-state-dot " + getStateDotClass(val);
          stateWrap.appendChild(dot);
          stateWrap.appendChild(document.createTextNode(val || ""));
          td.appendChild(stateWrap);
        } else if (col.isCost) {
          td.className = "resource-cost";
          var costType = col.key === "onDemandPrice" ? "ondemand" : "actual";
          if (val != null && val > 0) {
            td.dataset.rawValue = String(val);
            td.dataset.costType = costType;
            var converted = val * (COST_UNIT_MULTIPLIERS[costType][currentCostUnit] || 1);
            td.textContent = "$" + converted.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + currentCostUnit;
          } else if (val === 0) {
            td.textContent = "$0.00";
          } else {
            td.textContent = "\u2014";
            td.style.color = "var(--text-tertiary)";
          }
        } else if (col.key === "multiAz") {
          td.textContent = val ? "Yes" : "No";
        } else if (col.key === "creationDate" && val) {
          td.textContent = val.substring(0, 10);
        } else {
          td.textContent = val != null ? String(val) : "";
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  });

  var wrap = document.createElement("div");
  wrap.className = "resource-table-wrap";
  wrap.appendChild(table);
  drawerBodyEl.appendChild(wrap);
}

// ============================================================
// SSO Login
// ============================================================
var ssoLoginBtn = document.getElementById("sso-login-btn");
var ssoModal = document.getElementById("sso-modal");
var ssoModalClose = document.getElementById("sso-modal-close");
var ssoStepStart = document.getElementById("sso-step-start");
var ssoStepWaiting = document.getElementById("sso-step-waiting");
var ssoStepDone = document.getElementById("sso-step-done");
var ssoStepError = document.getElementById("sso-step-error");
var ssoStartBtn = document.getElementById("sso-start-btn");
var ssoUserCodeEl = document.getElementById("sso-user-code");
var ssoOpenLink = document.getElementById("sso-open-link");
var ssoErrorMsg = document.getElementById("sso-error-msg");
var ssoSessionSelectWrap = document.getElementById("sso-session-select-wrap");
var ssoSessionSelect = document.getElementById("sso-session-select");

function showSsoModal() {
  ssoStepStart.classList.remove("hidden");
  ssoStepWaiting.classList.add("hidden");
  ssoStepDone.classList.add("hidden");
  ssoStepError.classList.add("hidden");
  ssoModal.classList.remove("hidden");
  loadSsoSessions();
}

function hideSsoModal() {
  ssoModal.classList.add("hidden");
}

function showSsoStep(stepEl) {
  [ssoStepStart, ssoStepWaiting, ssoStepDone, ssoStepError].forEach(function(el) {
    el.classList.add("hidden");
  });
  stepEl.classList.remove("hidden");
}

async function loadSsoSessions() {
  try {
    var res = await fetch("/api/sso/sessions");
    if (!res.ok) return;
    var data = await res.json();
    if (data.sessions.length > 1) {
      while (ssoSessionSelect.firstChild) ssoSessionSelect.removeChild(ssoSessionSelect.firstChild);
      data.sessions.forEach(function(s) {
        var opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = s.name + " (" + s.start_url + ")";
        ssoSessionSelect.appendChild(opt);
      });
      ssoSessionSelectWrap.classList.remove("hidden");
    } else {
      ssoSessionSelectWrap.classList.add("hidden");
    }
  } catch (e) { /* ignore */ }
}

ssoLoginBtn.addEventListener("click", showSsoModal);
ssoModalClose.addEventListener("click", hideSsoModal);
ssoModal.addEventListener("click", function(e) { if (e.target === ssoModal) hideSsoModal(); });

ssoStartBtn.addEventListener("click", async function() {
  ssoStartBtn.disabled = true;
  try {
    var sessionParam = "";
    if (!ssoSessionSelectWrap.classList.contains("hidden")) {
      sessionParam = "?session_name=" + encodeURIComponent(ssoSessionSelect.value);
    }
    var res = await fetch("/api/sso/login" + sessionParam, { method: "POST" });
    if (!res.ok) {
      var err = await res.json();
      ssoErrorMsg.textContent = err.detail || "ログインの開始に失敗しました";
      showSsoStep(ssoStepError);
      ssoStartBtn.disabled = false;
      return;
    }
    var data = await res.json();
    ssoUserCodeEl.textContent = data.user_code;
    ssoOpenLink.href = data.verification_uri_complete;
    showSsoStep(ssoStepWaiting);

    // ブラウザで認証ページを開く
    window.open(data.verification_uri_complete, "_blank");

    // ポーリング開始
    var pollRes = await fetch("/api/sso/login/poll", { method: "POST" });
    var pollData = await pollRes.json();
    if (pollData.status === "success") {
      showSsoStep(ssoStepDone);
      setTimeout(function() {
        hideSsoModal();
        // 認証完了 → アカウント一覧を再読み込み
        loadAccounts().then(async function() {
          await loadServerDefaultAccountConfig();
          populateConfigAccountList();
          applyDefaultAccountSelection();
        });
      }, 1500);
    } else {
      ssoErrorMsg.textContent = pollData.message || "認証に失敗しました";
      showSsoStep(ssoStepError);
    }
  } catch (e) {
    ssoErrorMsg.textContent = "エラー: " + e.message;
    showSsoStep(ssoStepError);
  } finally {
    ssoStartBtn.disabled = false;
  }
});

// 401 エラー時にモーダルを自動表示
function showErrorWithSsoHint(msg) {
  showError(msg);
  showSsoModal();
}

// --- Init ---
loadAccounts().then(async function() {
  await loadServerDefaultAccountConfig();
  populateConfigAccountList();
  applyDefaultAccountSelection();
});
