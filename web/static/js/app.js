/**
 * NIFTY 500 Quantitative AI Terminal - Frontend Controller
 * Interacts with FastAPI SQLite Endpoints & Renders Dynamic Chart.js
 */

let priceChartInstance = null;
let marketAnalysisCache = null;
let activeTab = "bullish";

document.addEventListener("DOMContentLoaded", () => {
  const searchForm = document.getElementById("stock-search-form");
  const tickerInput = document.getElementById("ticker-input");
  const sectorFilter = document.getElementById("sector-filter");
  const analyzeBtn = document.getElementById("analyze-btn");
  const btnText = document.getElementById("btn-text");
  const loadingSpinner = document.getElementById("loading-spinner");
  const resultsContainer = document.getElementById("results-container");
  const chipButtons = document.querySelectorAll(".chip-btn[data-ticker]");
  const toggleButtons = document.querySelectorAll(".toggle-btn");
  const triggerCronBtn = document.getElementById("trigger-cron-btn");
  const cronBtnText = document.getElementById("cron-btn-text");

  const tabBullishBtn = document.getElementById("tab-bullish-btn");
  const tabBearishBtn = document.getElementById("tab-bearish-btn");

  // Handle Form Submit
  searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const ticker = tickerInput.value.trim().toUpperCase();
    if (ticker) {
      loadStockDetails(ticker);
    }
  });

  // Handle Quick Chips
  chipButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const ticker = btn.getAttribute("data-ticker");
      tickerInput.value = ticker;
      loadStockDetails(ticker);
    });
  });

  // Handle Chart Toggles
  toggleButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const datasetType = btn.getAttribute("data-dataset");
      btn.classList.toggle("active");
      toggleChartDataset(datasetType, btn.classList.contains("active"));
    });
  });

  // Handle Opportunity Tabs
  tabBullishBtn.addEventListener("click", () => {
    activeTab = "bullish";
    tabBullishBtn.classList.add("active");
    tabBearishBtn.classList.remove("active");
    renderOpportunitiesTable();
  });

  tabBearishBtn.addEventListener("click", () => {
    activeTab = "bearish";
    tabBearishBtn.classList.add("active");
    tabBullishBtn.classList.remove("active");
    renderOpportunitiesTable();
  });

  // Handle Manual Trailing Cron Trigger
  if (triggerCronBtn) {
    triggerCronBtn.addEventListener("click", async () => {
      cronBtnText.textContent = "Syncing...";
      triggerCronBtn.disabled = true;
      try {
        const resp = await fetch("/api/cron/run", { method: "POST" });
        const res = await resp.json();
        alert("Trailing sync launched in background: " + res.message);
        setTimeout(() => {
          loadMarketAnalysis();
          cronBtnText.textContent = "Sync Trailing Data";
          triggerCronBtn.disabled = false;
        }, 3000);
      } catch (err) {
        alert("Error launching cron: " + err.message);
        cronBtnText.textContent = "Sync Trailing Data";
        triggerCronBtn.disabled = false;
      }
    });
  }

  // Handle Model Training Initiator & Real-Time Status Polling
  const startTrainBtn = document.getElementById("start-train-all-btn");
  const headerTrainBtn = document.getElementById("header-train-all-btn");
  const trainBtnText = document.getElementById("train-btn-text");
  const headerTrainBtnText = document.getElementById("header-train-btn-text");

  const statusBadge = document.getElementById("train-status-badge");
  const currentTickerText = document.getElementById("train-current-ticker");
  const countText = document.getElementById("train-count-text");
  const progressFill = document.getElementById("train-progress-fill");
  const trainMessageText = document.getElementById("train-message");
  const trainElapsedText = document.getElementById("train-elapsed");

  let trainPollInterval = null;

  async function initiateModelTraining() {
    if (confirm("Initiate batch model training & retraining across all 500 NIFTY stocks with today's latest data?")) {
      setTrainingBtnState(true, "Initiating...");
      try {
        const resp = await fetch("/api/models/init-all?force=true", { method: "POST" });
        const data = await resp.json();
        console.log("Model training initiated:", data);
        startTrainingPolling();
      } catch (err) {
        alert("Failed to initiate model training: " + err.message);
        setTrainingBtnState(false, "Initiate Training (All 500 Models)");
      }
    }
  }

  function setTrainingBtnState(disabled, text) {
    if (startTrainBtn) {
      startTrainBtn.disabled = disabled;
      if (trainBtnText) trainBtnText.textContent = text;
    }
    if (headerTrainBtn) {
      headerTrainBtn.disabled = disabled;
      if (headerTrainBtnText) headerTrainBtnText.textContent = disabled ? "Training..." : "Train All Models";
    }
  }

  function startTrainingPolling() {
    if (trainPollInterval) clearInterval(trainPollInterval);
    pollTrainingStatus();
    trainPollInterval = setInterval(pollTrainingStatus, 1500);
  }

  async function pollTrainingStatus() {
    try {
      const resp = await fetch("/api/models/status");
      if (!resp.ok) return;
      const data = await resp.json();

      const st = data.status || "idle";
      const pct = data.progress_pct || 0.0;
      const completed = data.completed_stocks || 0;
      const total = data.total_stocks || 501;

      if (statusBadge) {
        statusBadge.textContent = `Status: ${st.toUpperCase()}`;
        statusBadge.className = `progress-status-badge ${st}`;
      }

      if (progressFill) {
        progressFill.style.width = `${pct.toFixed(1)}%`;
      }

      if (countText) {
        countText.textContent = `${completed} / ${total} Stocks (${pct.toFixed(1)}%)`;
      }

      if (currentTickerText) {
        currentTickerText.textContent = data.current_ticker ? `Training: ${data.current_ticker}` : `Task: ${data.task_type || "idle"}`;
      }

      if (trainMessageText && data.message) {
        trainMessageText.textContent = data.message;
      }

      if (trainElapsedText && data.elapsed_seconds) {
        trainElapsedText.textContent = `Elapsed: ${data.elapsed_seconds.toFixed(0)}s`;
      }

      if (st === "running") {
        setTrainingBtnState(true, `Training (${pct.toFixed(0)}%)`);
      } else if (st === "completed" || st === "idle" || st === "failed") {
        setTrainingBtnState(false, "Initiate Training (All 500 Models)");
        if (trainPollInterval && st !== "running") {
          clearInterval(trainPollInterval);
          trainPollInterval = null;
        }
        if (st === "completed") {
          loadMarketAnalysis();
          loadMarketSegmentation();
        }
      }
    } catch (err) {
      console.log("Error polling training status:", err);
    }
  }

  if (startTrainBtn) startTrainBtn.addEventListener("click", initiateModelTraining);
  if (headerTrainBtn) headerTrainBtn.addEventListener("click", initiateModelTraining);

  // Poll status on boot
  pollTrainingStatus();

  // Initial Boot
  loadStockDetails("RELIANCE");
  loadMarketAnalysis();
  loadMarketSegmentation();

  /**
   * Loads consolidated stock details from GET /api/stock/{ticker}
   */
  async function loadStockDetails(ticker) {
    setLoading(true);
    try {
      const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}`);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to load stock data");
      }
      const data = await res.json();
      setLoading(false);
      renderStockDashboard(data);
    } catch (err) {
      setLoading(false);
      alert(`Error loading ${ticker}: ${err.message}`);
      console.error(err);
    }
  }

  function setLoading(isLoading) {
    if (isLoading) {
      loadingSpinner.classList.remove("hidden");
      resultsContainer.classList.add("hidden");
      analyzeBtn.disabled = true;
      btnText.textContent = "Loading...";
    } else {
      loadingSpinner.classList.add("hidden");
      resultsContainer.classList.remove("hidden");
      analyzeBtn.disabled = false;
      btnText.textContent = "Get Stock Forecast";
    }
  }

  /**
   * Renders the consolidated stock dashboard
   */
  function renderStockDashboard(data) {
    const cur = data.currency_symbol || "₹";
    const meta = data.fundamentals || {};
    const ohlcv = data.latest_ohlcv || {};
    const ind = data.technicals || {};
    const pred = data.prediction || {};
    const chartHistory = data.chart_history || [];

    // Header & Ticker
    document.getElementById("ticker-badge").textContent = data.ticker;
    document.getElementById("company-name-text").textContent = meta.company_name || data.ticker;
    document.getElementById("as-of-date").textContent = `As of: ${ohlcv.date || "Latest"}`;

    // Trend Badge
    const trend = (pred.trend_signal || "BULLISH").toUpperCase();
    const isBullish = trend === "BULLISH";
    const trendBadge = document.getElementById("trend-badge");
    const trendIcon = document.getElementById("trend-icon");
    const trendText = document.getElementById("trend-text");

    trendBadge.className = `trend-badge ${isBullish ? "bullish" : "bearish"}`;
    trendIcon.textContent = isBullish ? "▲" : "▼";
    trendText.textContent = trend;

    // Price Card
    const closePrice = ohlcv.close || pred.reference_close || 0.0;
    const predPrice = pred.predicted_close || closePrice;
    const dayChange = data.day_change || 0.0;
    const dayChangePct = data.day_change_pct || 0.0;
    const expChange = pred.expected_pct_change || 0.0;
    const expDelta = predPrice - closePrice;

    document.getElementById("ref-price-val").textContent = `${cur}${closePrice.toFixed(2)}`;
    const dayChangeElem = document.getElementById("day-change-val");
    const daySign = dayChange >= 0 ? "+" : "";
    dayChangeElem.textContent = `${daySign}${cur}${dayChange.toFixed(2)} (${daySign}${dayChangePct.toFixed(2)}%)`;
    dayChangeElem.className = `price-delta ${dayChange >= 0 ? "positive" : "negative"}`;

    document.getElementById("predicted-close-val").textContent = `${cur}${predPrice.toFixed(2)}`;
    const expDeltaElem = document.getElementById("price-delta-val");
    const expSign = expDelta >= 0 ? "+" : "";
    expDeltaElem.textContent = `${expSign}${cur}${expDelta.toFixed(2)} (${expSign}${expChange.toFixed(2)}%)`;
    expDeltaElem.className = `price-delta ${expDelta >= 0 ? "positive" : "negative"}`;

    const rLow = pred.range_low || closePrice * 0.98;
    const rHigh = pred.range_high || closePrice * 1.02;
    document.getElementById("expected-range-val").textContent = `${cur}${rLow.toFixed(2)} - ${cur}${rHigh.toFixed(2)}`;
    document.getElementById("confidence-val").textContent = `${(pred.confidence_pct || 65.0).toFixed(1)}%`;
    document.getElementById("target-date-val").textContent = pred.target_date || "Tomorrow";

    // Probability Bar
    const conf = pred.confidence_pct || 60.0;
    const bullProb = isBullish ? conf : 100.0 - conf;
    const bearProb = 100.0 - bullProb;
    document.getElementById("prob-bullish-label").textContent = `Bullish: ${bullProb.toFixed(1)}%`;
    document.getElementById("prob-bearish-label").textContent = `Bearish: ${bearProb.toFixed(1)}%`;
    document.getElementById("prob-bar-fill").style.width = `${bullProb}%`;

    // Render Next-Hour Intraday Prediction Card
    const nextHourPred = data.next_hour_prediction || {};
    const nextHourTickerBadge = document.getElementById("next-hour-ticker-badge");
    if (nextHourTickerBadge) nextHourTickerBadge.textContent = data.ticker;

    const nextHourTrend = (nextHourPred.trend_signal || "BULLISH").toUpperCase();
    const isNextHourBullish = nextHourTrend === "BULLISH";
    const nextHourBadge = document.getElementById("next-hour-trend-badge");
    const nextHourIcon = document.getElementById("next-hour-trend-icon");
    const nextHourText = document.getElementById("next-hour-trend-text");

    if (nextHourBadge) nextHourBadge.className = `trend-badge ${isNextHourBullish ? "bullish" : "bearish"}`;
    if (nextHourIcon) nextHourIcon.textContent = isNextHourBullish ? "▲" : "▼";
    if (nextHourText) nextHourText.textContent = nextHourTrend;

    const nextHourRefPrice = nextHourPred.reference_close || closePrice;
    const nextHourTargetPrice = nextHourPred.predicted_close || nextHourRefPrice;
    const nextHourExpChange = nextHourPred.expected_pct_change || 0.0;
    const nextHourDelta = nextHourTargetPrice - nextHourRefPrice;

    const nhRefElem = document.getElementById("next-hour-ref-price");
    if (nhRefElem) nhRefElem.textContent = `${cur}${nextHourRefPrice.toFixed(2)}`;

    const nhPredElem = document.getElementById("next-hour-predicted-close");
    if (nhPredElem) nhPredElem.textContent = `${cur}${nextHourTargetPrice.toFixed(2)}`;

    const nhDeltaElem = document.getElementById("next-hour-price-delta");
    if (nhDeltaElem) {
      const nhSign = nextHourDelta >= 0 ? "+" : "";
      nhDeltaElem.textContent = `${nhSign}${cur}${nextHourDelta.toFixed(2)} (${nhSign}${nextHourExpChange.toFixed(2)}%)`;
      nhDeltaElem.className = `price-delta ${nextHourDelta >= 0 ? "positive" : "negative"}`;
    }

    const nhRLow = nextHourPred.range_low || nextHourRefPrice * 0.99;
    const nhRHigh = nextHourPred.range_high || nextHourRefPrice * 1.01;
    const nhRangeElem = document.getElementById("next-hour-expected-range");
    if (nhRangeElem) nhRangeElem.textContent = `${cur}${nhRLow.toFixed(2)} - ${cur}${nhRHigh.toFixed(2)}`;

    const nhConfElem = document.getElementById("next-hour-confidence");
    if (nhConfElem) nhConfElem.textContent = `${(nextHourPred.confidence_pct || 60.0).toFixed(1)}%`;

    const nhTargetDateElem = document.getElementById("next-hour-target-date");
    if (nhTargetDateElem) nhTargetDateElem.textContent = nextHourPred.target_date || "Next Trading Hour";

    const nhConf = nextHourPred.confidence_pct || 60.0;
    const nhBullProb = isNextHourBullish ? nhConf : 100.0 - nhConf;
    const nhBearProb = 100.0 - nhBullProb;
    const nhBullLabel = document.getElementById("next-hour-prob-bullish-label");
    if (nhBullLabel) nhBullLabel.textContent = `Bullish: ${nhBullProb.toFixed(1)}%`;
    const nhBearLabel = document.getElementById("next-hour-prob-bearish-label");
    if (nhBearLabel) nhBearLabel.textContent = `Bearish: ${nhBearProb.toFixed(1)}%`;
    const nhBarFill = document.getElementById("next-hour-prob-bar-fill");
    if (nhBarFill) nhBarFill.style.width = `${nhBullProb}%`;

    // Fundamentals
    document.getElementById("val-sector").textContent = meta.sector || meta.industry || "NIFTY 500";
    document.getElementById("val-industry").textContent = meta.industry || "General";
    document.getElementById("val-mcap").textContent = meta.market_cap ? `₹${Number(meta.market_cap).toLocaleString()} Cr` : "N/A";
    document.getElementById("val-pe").textContent = meta.pe_ratio ? meta.pe_ratio.toFixed(2) : "N/A";
    document.getElementById("val-pb").textContent = meta.pb_ratio ? meta.pb_ratio.toFixed(2) : "N/A";
    document.getElementById("val-eps").textContent = meta.eps ? `₹${meta.eps.toFixed(2)}` : "N/A";
    document.getElementById("val-div").textContent = meta.dividend_yield ? `${meta.dividend_yield.toFixed(2)}%` : "0.0%";
    document.getElementById("val-roe").textContent = meta.roe ? `${meta.roe.toFixed(2)}%` : "N/A";

    // Technical Indicators
    const rsi = ind.rsi_14 || 50.0;
    document.getElementById("val-rsi").textContent = rsi.toFixed(1);
    document.getElementById("rsi-meter").style.width = `${Math.min(100, Math.max(0, rsi))}%`;
    const rsiTag = document.getElementById("rsi-tag");
    if (rsi >= 70) {
      rsiTag.textContent = "Overbought";
      rsiTag.className = "status-tag bearish";
    } else if (rsi <= 30) {
      rsiTag.textContent = "Oversold";
      rsiTag.className = "status-tag bullish";
    } else {
      rsiTag.textContent = "Neutral";
      rsiTag.className = "status-tag";
    }

    const macdHist = ind.macd_hist || 0.0;
    const macdHistElem = document.getElementById("val-macd-hist");
    macdHistElem.textContent = `${macdHist >= 0 ? "+" : ""}${macdHist.toFixed(2)}`;
    macdHistElem.style.color = macdHist >= 0 ? "var(--accent-bullish)" : "var(--accent-bearish)";
    document.getElementById("val-macd").textContent = (ind.macd || 0.0).toFixed(2);
    document.getElementById("val-macd-signal").textContent = (ind.macd_signal || 0.0).toFixed(2);
    const macdTag = document.getElementById("macd-tag");
    if ((ind.macd || 0) > (ind.macd_signal || 0)) {
      macdTag.textContent = "Bullish Cross";
      macdTag.className = "status-tag bullish";
    } else {
      macdTag.textContent = "Bearish Cross";
      macdTag.className = "status-tag bearish";
    }

    document.getElementById("val-bb-upper").textContent = `${cur}${(ind.bb_upper || closePrice * 1.05).toFixed(2)}`;
    document.getElementById("val-bb-mid").textContent = `${cur}${(ind.bb_middle || closePrice).toFixed(2)}`;
    document.getElementById("val-bb-lower").textContent = `${cur}${(ind.bb_lower || closePrice * 0.95).toFixed(2)}`;

    document.getElementById("val-res-r1").textContent = `${cur}${(ind.pivot_r1 || closePrice * 1.02).toFixed(2)}`;
    document.getElementById("val-pivot").textContent = `${cur}${(ind.pivot_p || closePrice).toFixed(2)}`;
    document.getElementById("val-sup-s1").textContent = `${cur}${(ind.pivot_s1 || closePrice * 0.98).toFixed(2)}`;

    document.getElementById("val-sma-20").textContent = `${cur}${(ind.sma_20 || closePrice).toFixed(2)}`;
    document.getElementById("val-sma-50").textContent = `${cur}${(ind.sma_50 || closePrice).toFixed(2)}`;
    document.getElementById("val-sma-200").textContent = `${cur}${(ind.sma_200 || closePrice).toFixed(2)}`;
    const maTag = document.getElementById("ma-trend-tag");
    if (closePrice > (ind.sma_50 || 0) && (ind.sma_50 || 0) > (ind.sma_200 || 0)) {
      maTag.textContent = "Strong Uptrend";
      maTag.className = "status-tag bullish";
    } else if (closePrice < (ind.sma_50 || closePrice)) {
      maTag.textContent = "Downtrend";
      maTag.className = "status-tag bearish";
    } else {
      maTag.textContent = "Consolidating";
      maTag.className = "status-tag";
    }

    document.getElementById("val-atr").textContent = `${cur}${(ind.atr_14 || closePrice * 0.02).toFixed(2)}`;
    document.getElementById("val-adx").textContent = `${(ind.adx_14 || 20.0).toFixed(1)} ${ind.adx_14 >= 25 ? "(Trending)" : "(Ranging)"}`;
    document.getElementById("val-bb-bw").textContent = (ind.bb_bandwidth || 0.05).toFixed(3);

    // Render AI Optimization & False Positive Audit Tags
    const elimContainer = document.getElementById("elimination-tags-list");
    if (elimContainer) {
      elimContainer.innerHTML = "";
      const factors = pred.elimination_factors || [];
      if (factors.length === 0) {
        elimContainer.innerHTML = `<span class="elim-tag positive">Clean Confluence Signal (No Damping Required)</span>`;
      } else {
        factors.forEach((f) => {
          const isDamped = f.toLowerCase().includes("damped") || f.toLowerCase().includes("eliminated");
          const isPos = f.toLowerCase().includes("confluence") || f.toLowerCase().includes("breakout") || f.toLowerCase().includes("consensus");
          let cls = "elim-tag";
          if (isPos) cls += " positive";
          else if (isDamped) cls += " damped";
          else cls += " eliminated";
          elimContainer.innerHTML += `<span class="${cls}">${f}</span>`;
        });
      }
    }

    // Render All 4 Technical Graphs
    renderAllSubCharts(chartHistory, predPrice, cur);
  }

  let priceChartInstance = null;
  let rsiChartInstance = null;
  let macdChartInstance = null;
  let volumeChartInstance = null;

  /**
   * Renders the interactive multi-graph technical analysis suite in Smooth Dark Mild Colors
   */
  function renderAllSubCharts(history, nextPredClose, cur) {
    if (!history || history.length === 0) return;

    const labels = history.map((d) => d.date);
    const closePrices = history.map((d) => d.close);
    const sma200 = history.map((d) => d.sma_200);
    const pivotR1 = history.map((d) => d.pivot_r1);
    const pivotS1 = history.map((d) => d.pivot_s1);

    const rsiList = history.map((d) => d.rsi_14 || 50.0);
    const macdList = history.map((d) => d.macd || 0.0);
    const macdSignalList = history.map((d) => d.macd_signal || 0.0);
    const macdHistList = history.map((d) => d.macd_hist || 0.0);
    const volList = history.map((d) => d.volume || 0.0);

    const extendedLabels = [...labels, "Tomorrow"];
    const forecastData = new Array(labels.length).fill(null);
    forecastData[labels.length - 1] = closePrices[closePrices.length - 1];
    forecastData.push(nextPredClose);

    const isBullishForecast = nextPredClose >= closePrices[closePrices.length - 1];

    // 1. Primary Price & Overlays Chart (Smooth Cyan & Emerald/Rose Forecast)
    const priceCtx = document.getElementById("price-chart").getContext("2d");
    if (priceChartInstance) priceChartInstance.destroy();

    priceChartInstance = new Chart(priceCtx, {
      type: "line",
      data: {
        labels: extendedLabels,
        datasets: [
          {
            label: "Close Price",
            data: [...closePrices, null],
            borderColor: "#38bdf8",
            backgroundColor: "rgba(56, 189, 248, 0.08)",
            borderWidth: 2.5,
            tension: 0.15,
            pointRadius: 0,
            fill: true,
          },
          {
            label: "ML Target Forecast",
            data: forecastData,
            borderColor: isBullishForecast ? "#10b981" : "#f43f5e",
            borderDash: [5, 5],
            borderWidth: 2.5,
            pointRadius: [0, 5],
            pointBackgroundColor: isBullishForecast ? "#10b981" : "#f43f5e",
          },
          {
            label: "SMA 20",
            data: [...sma20, null],
            borderColor: "#c59e00",
            borderWidth: 2,
            pointRadius: 0,
          },
          {
            label: "SMA 50",
            data: [...sma50, null],
            borderColor: "#a855f7",
            borderWidth: 2,
            pointRadius: 0,
          },
          {
            label: "SMA 200",
            data: [...sma200, null],
            borderColor: "#ec4899",
            borderWidth: 2,
            pointRadius: 0,
            hidden: true,
          },
          {
            label: "Bollinger Upper",
            data: [...bbUpper, null],
            borderColor: "rgba(255, 255, 255, 0.35)",
            borderDash: [3, 3],
            borderWidth: 1.2,
            pointRadius: 0,
          },
          {
            label: "Bollinger Lower",
            data: [...bbLower, null],
            borderColor: "rgba(255, 255, 255, 0.35)",
            borderDash: [3, 3],
            borderWidth: 1.2,
            pointRadius: 0,
          },
          {
            label: "Resistance R1",
            data: [...pivotR1, null],
            borderColor: "rgba(244, 63, 94, 0.75)",
            borderDash: [6, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            hidden: true,
          },
          {
            label: "Support S1",
            data: [...pivotS1, null],
            borderColor: "rgba(16, 185, 129, 0.75)",
            borderDash: [6, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            hidden: true,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } } },
          x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" }, maxRotation: 45 } }
        },
        plugins: {
          legend: { display: true, labels: { color: "#cbd5e1", font: { family: "Outfit", size: 11 } } }
        }
      }
    });

    // 2. RSI Sub-Chart Graph
    const rsiCanvas = document.getElementById("rsi-chart");
    if (rsiCanvas) {
      const rsiCtx = rsiCanvas.getContext("2d");
      if (rsiChartInstance) rsiChartInstance.destroy();
      rsiChartInstance = new Chart(rsiCtx, {
        type: "line",
        data: {
          labels: labels,
          datasets: [
            {
              label: "RSI (14)",
              data: rsiList,
              borderColor: "#c084fc",
              borderWidth: 2,
              pointRadius: 0,
              tension: 0.1,
            },
            {
              label: "Overbought (70)",
              data: new Array(labels.length).fill(70),
              borderColor: "rgba(244, 63, 94, 0.6)",
              borderDash: [4, 4],
              borderWidth: 1,
              pointRadius: 0,
            },
            {
              label: "Oversold (30)",
              data: new Array(labels.length).fill(30),
              borderColor: "rgba(16, 185, 129, 0.6)",
              borderDash: [4, 4],
              borderWidth: 1,
              pointRadius: 0,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { min: 0, max: 100, grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } } },
            x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } } }
          },
          plugins: { legend: { display: true, labels: { color: "#cbd5e1", font: { family: "Outfit", size: 10 } } } }
        }
      });
    }

    // 3. MACD Sub-Chart Graph
    const macdCanvas = document.getElementById("macd-chart");
    if (macdCanvas) {
      const macdCtx = macdCanvas.getContext("2d");
      if (macdChartInstance) macdChartInstance.destroy();
      const macdHistColors = macdHistList.map((v) => (v >= 0 ? "rgba(16, 185, 129, 0.7)" : "rgba(244, 63, 94, 0.7)"));

      macdChartInstance = new Chart(macdCtx, {
        data: {
          labels: labels,
          datasets: [
            {
              type: "bar",
              label: "MACD Hist",
              data: macdHistList,
              backgroundColor: macdHistColors,
            },
            {
              type: "line",
              label: "MACD Line",
              data: macdList,
              borderColor: "#38bdf8",
              borderWidth: 1.8,
              pointRadius: 0,
            },
            {
              type: "line",
              label: "Signal Line",
              data: macdSignalList,
              borderColor: "#fbbf24",
              borderWidth: 1.5,
              pointRadius: 0,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } } },
            x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } } }
          },
          plugins: { legend: { display: true, labels: { color: "#cbd5e1", font: { family: "Outfit", size: 10 } } } }
        }
      });
    }

    // 4. Volume Sub-Chart Graph
    const volCanvas = document.getElementById("volume-chart");
    if (volCanvas) {
      const volCtx = volCanvas.getContext("2d");
      if (volumeChartInstance) volumeChartInstance.destroy();
      volumeChartInstance = new Chart(volCtx, {
        type: "bar",
        data: {
          labels: labels,
          datasets: [
            {
              label: "Volume",
              data: volList,
              backgroundColor: "rgba(56, 189, 248, 0.4)",
              borderColor: "#38bdf8",
              borderWidth: 1,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } } },
            x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } } }
          },
          plugins: { legend: { display: false } }
        }
      });
    }
  }

  function toggleChartDataset(type, isVisible) {
    if (!priceChartInstance) return;
    if (type === "close") priceChartInstance.setDatasetVisibility(0, isVisible);
    else if (type === "sma20") priceChartInstance.setDatasetVisibility(2, isVisible);
    else if (type === "sma50") priceChartInstance.setDatasetVisibility(3, isVisible);
    else if (type === "sma200") priceChartInstance.setDatasetVisibility(4, isVisible);
    else if (type === "bb") {
      priceChartInstance.setDatasetVisibility(5, isVisible);
      priceChartInstance.setDatasetVisibility(6, isVisible);
    } else if (type === "pivots") {
      priceChartInstance.setDatasetVisibility(7, isVisible);
      priceChartInstance.setDatasetVisibility(8, isVisible);
    }
    priceChartInstance.update();
  }

  /**
   * Loads Market Breadth & Daily Scanner via GET /api/market/analysis
   */
  async function loadMarketAnalysis() {
    try {
      const res = await fetch("/api/market/analysis");
      if (!res.ok) return;
      const data = await res.json();
      marketAnalysisCache = data.market_analysis || {};

      // Breadth stats
      document.getElementById("breadth-advances").textContent = marketAnalysisCache.advances || 0;
      document.getElementById("breadth-declines").textContent = marketAnalysisCache.declines || 0;
      document.getElementById("breadth-sma50").textContent = `${marketAnalysisCache.pct_above_sma50 || 0}%`;
      document.getElementById("breadth-sma200").textContent = `${marketAnalysisCache.pct_above_sma200 || 0}%`;

      // Sector performance list
      const sectorList = document.getElementById("sector-heat-list");
      sectorList.innerHTML = "";
      const sectors = marketAnalysisCache.sector_performance || {};
      for (const [sec, ret] of Object.entries(sectors)) {
        const isPos = ret >= 0;
        const div = document.createElement("div");
        div.className = "sector-heat-item";
        div.innerHTML = `
          <span class="sec-name">${sec}</span>
          <span class="sec-val font-mono ${isPos ? 'positive' : 'negative'}">${isPos ? '+' : ''}${ret.toFixed(2)}%</span>
        `;
        sectorList.appendChild(div);
      }

      renderOpportunitiesTable();
    } catch (e) {
      console.log("Market analysis load note:", e);
    }
  }

  /**
   * Renders Top Opportunities Table
   */
  function renderOpportunitiesTable() {
    if (!marketAnalysisCache) return;
    const tbody = document.getElementById("opportunities-body");
    tbody.innerHTML = "";

    const list = activeTab === "bullish"
      ? (marketAnalysisCache.top_bullish_tickers || [])
      : (marketAnalysisCache.top_bearish_tickers || []);

    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">No records found.</td></tr>`;
      return;
    }

    list.slice(0, 8).forEach((item) => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => {
        document.getElementById("ticker-input").value = item.ticker.replace(".NS", "");
        loadStockDetails(item.ticker);
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      const isPos = item.expected_pct_change >= 0;
      tr.innerHTML = `
        <td><strong>${item.ticker.replace(".NS", "")}</strong> <small style="display:block; color:var(--text-dim);">${item.sector || ''}</small></td>
        <td>₹${item.close ? item.close.toFixed(2) : '-'}</td>
        <td class="${isPos ? 'positive' : 'negative'}">${isPos ? '+' : ''}${item.expected_pct_change.toFixed(2)}%</td>
        <td>${item.confidence_pct ? item.confidence_pct.toFixed(1) + '%' : '-'}</td>
        <td>${item.rsi_14 || '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  /* =====================================================================
     Industry & Sentiment Segmentation Matrix Controller
     ===================================================================== */
  let segmentationCache = null;
  let activeConvictionTier = "all";
  let activeIndustryFilter = "";

  const segIndustrySelect = document.getElementById("seg-industry-filter");
  const sentimentCards = document.querySelectorAll(".sentiment-card");
  const tierChips = document.querySelectorAll(".tier-chip");

  // Handle Sentiment Card Click
  sentimentCards.forEach((card) => {
    card.addEventListener("click", () => {
      const seg = card.getAttribute("data-segment");
      if (activeConvictionTier === seg) {
        activeConvictionTier = "all";
      } else {
        activeConvictionTier = seg;
      }
      updateActiveFilterUI();
      renderSegmentedStocksTable();
    });
  });

  // Handle Quick Tier Chip Click
  tierChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      activeConvictionTier = chip.getAttribute("data-filter");
      updateActiveFilterUI();
      renderSegmentedStocksTable();
    });
  });

  // Handle Industry Select Dropdown
  if (segIndustrySelect) {
    segIndustrySelect.addEventListener("change", (e) => {
      activeIndustryFilter = e.target.value;
      highlightActiveRadarIndustry();
      renderSegmentedStocksTable();
    });
  }

  function updateActiveFilterUI() {
    tierChips.forEach((chip) => {
      if (chip.getAttribute("data-filter") === activeConvictionTier) {
        chip.classList.add("active");
      } else {
        chip.classList.remove("active");
      }
    });

    sentimentCards.forEach((card) => {
      if (card.getAttribute("data-segment") === activeConvictionTier) {
        card.classList.add("active");
      } else {
        card.classList.remove("active");
      }
    });
  }

  function highlightActiveRadarIndustry() {
    const items = document.querySelectorAll(".industry-radar-item");
    items.forEach((item) => {
      if (item.getAttribute("data-sector") === activeIndustryFilter) {
        item.classList.add("active");
      } else {
        item.classList.remove("active");
      }
    });
  }

  /**
   * Loads Market Segmentation via GET /api/market/segmentation
   */
  async function loadMarketSegmentation() {
    try {
      const res = await fetch("/api/market/segmentation");
      if (!res.ok) return;
      const data = await res.json();
      segmentationCache = data;

      // Update 6 Conviction Distribution Cards
      const counts = data.sentiment_counts || {};
      const tiers = [
        "extreme_bullish",
        "medium_bullish",
        "mild_bullish",
        "mild_bearish",
        "medium_bearish",
        "extreme_bearish",
      ];

      tiers.forEach((t) => {
        const item = counts[t] || { count: 0, pct: 0 };
        const countElem = document.getElementById(`sent-count-${t.replace(/_/g, "-")}`);
        const pctElem = document.getElementById(`sent-pct-${t.replace(/_/g, "-")}`);
        if (countElem) countElem.textContent = item.count;
        if (pctElem) pctElem.textContent = `${item.pct.toFixed(1)}%`;
      });

      // Populate Industry Select Dropdown
      if (segIndustrySelect && data.sectors) {
        segIndustrySelect.innerHTML = `<option value="">All Industries (${data.total_stocks} stocks)</option>`;
        data.sectors.forEach((sec) => {
          const opt = document.createElement("option");
          opt.value = sec.sector;
          opt.textContent = `${sec.sector} (${sec.total_stocks} stocks)`;
          segIndustrySelect.appendChild(opt);
        });
      }

      const countTag = document.getElementById("industry-count-tag");
      if (countTag && data.sectors) {
        countTag.textContent = `${data.sectors.length} Industries`;
      }

      renderIndustryRadarList();
      renderSegmentedStocksTable();
    } catch (err) {
      console.log("Market segmentation load note:", err);
    }
  }

  /**
   * Renders the Industry Sentiment Radar list on the left
   */
  function renderIndustryRadarList() {
    if (!segmentationCache || !segmentationCache.sectors) return;
    const container = document.getElementById("industry-radar-list");
    if (!container) return;
    container.innerHTML = "";

    segmentationCache.sectors.forEach((sec) => {
      const div = document.createElement("div");
      div.className = "industry-radar-item";
      div.setAttribute("data-sector", sec.sector);
      if (activeIndustryFilter === sec.sector) {
        div.classList.add("active");
      }

      let biasClass = "balanced";
      let biasLabel = "Balanced";
      if (sec.bias && sec.bias.includes("BULLISH")) {
        biasClass = "bullish";
        biasLabel = "Bullish";
      } else if (sec.bias && sec.bias.includes("BEARISH")) {
        biasClass = "bearish";
        biasLabel = "Bearish";
      }

      div.innerHTML = `
        <div class="ind-row-top">
          <span class="ind-name">${sec.sector}</span>
          <span class="ind-bias-pill ${biasClass}">${biasLabel}</span>
        </div>
        <div class="ind-ratio-bar">
          <div class="ind-ratio-fill" style="width: ${sec.bullish_pct}%;"></div>
        </div>
        <div class="ind-counts-row">
          <span>${sec.total_stocks} stocks</span>
          <span>Bull: ${sec.bullish_count} | Bear: ${sec.bearish_count}</span>
        </div>
      `;

      div.addEventListener("click", () => {
        if (activeIndustryFilter === sec.sector) {
          activeIndustryFilter = "";
        } else {
          activeIndustryFilter = sec.sector;
        }
        if (segIndustrySelect) {
          segIndustrySelect.value = activeIndustryFilter;
        }
        highlightActiveRadarIndustry();
        renderSegmentedStocksTable();
      });

      container.appendChild(div);
    });
  }

  /**
   * Renders the interactive table of segmented stocks
   */
  function renderSegmentedStocksTable() {
    if (!segmentationCache || !segmentationCache.stocks) return;
    const tbody = document.getElementById("segment-stocks-tbody");
    const countBadge = document.getElementById("segment-stocks-count");
    const subTitle = document.getElementById("segment-table-sub");
    if (!tbody) return;

    let filtered = segmentationCache.stocks;

    // Filter by Industry
    if (activeIndustryFilter) {
      filtered = filtered.filter((s) => s.sector === activeIndustryFilter);
    }

    // Filter by Conviction Tier
    if (activeConvictionTier && activeConvictionTier !== "all") {
      filtered = filtered.filter((s) => s.segment_key === activeConvictionTier);
    }

    if (countBadge) {
      countBadge.textContent = `${filtered.length} stocks`;
    }

    if (subTitle) {
      const indLabel = activeIndustryFilter || "All Industries";
      const tierLabel = activeConvictionTier === "all" ? "All Conviction Tiers" : activeConvictionTier.replace(/_/g, " ").toUpperCase();
      subTitle.textContent = `${indLabel} • ${tierLabel}`;
    }

    tbody.innerHTML = "";
    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color:var(--text-muted);">No constituents match the selected industry and conviction tier.</td></tr>`;
      return;
    }

    filtered.slice(0, 60).forEach((item) => {
      const tr = document.createElement("tr");
      tr.addEventListener("click", () => {
        const cleanTicker = item.ticker.replace(".NS", "");
        document.getElementById("ticker-input").value = cleanTicker;
        loadStockDetails(cleanTicker);
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      const isPos = item.expected_pct_change >= 0;
      let badgeClass = item.segment_key.replace(/_/g, "-");
      let icon = "🌱";
      if (item.segment_key === "extreme_bullish") icon = "⚡";
      else if (item.segment_key === "medium_bullish") icon = "📈";
      else if (item.segment_key === "mild_bearish") icon = "🍂";
      else if (item.segment_key === "medium_bearish") icon = "📉";
      else if (item.segment_key === "extreme_bearish") icon = "🚨";

      tr.innerHTML = `
        <td>
          <strong style="color:var(--text-main); font-weight:700;">${item.ticker.replace(".NS", "")}</strong>
          <small style="display:block; color:var(--text-dim); font-size:0.75rem;">${item.company_name || ''}</small>
        </td>
        <td><span style="font-size:0.78rem; color:var(--text-muted);">${item.sector || ''}</span></td>
        <td class="font-mono">₹${item.close ? item.close.toFixed(2) : '-'}</td>
        <td class="font-mono">₹${item.predicted_close ? item.predicted_close.toFixed(2) : '-'}</td>
        <td class="font-mono ${isPos ? 'positive' : 'negative'}"><strong>${isPos ? '+' : ''}${item.expected_pct_change.toFixed(2)}%</strong></td>
        <td class="font-mono">${item.confidence_pct ? item.confidence_pct.toFixed(1) + '%' : '-'}</td>
        <td class="font-mono">${item.rsi_14 !== null && item.rsi_14 !== undefined ? item.rsi_14 : '-'}</td>
        <td><span class="conviction-badge ${badgeClass}">${icon} ${item.segment_label}</span></td>
      `;

      tbody.appendChild(tr);
    });
  }
});
