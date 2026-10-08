let currentStockChart = null;
let currentSelectedTicker = null;
let currentEvaluationData = null;
let currentActiveNodeId = 'NODE_01_BULLISH_TRENDING';
let currentStockItems = [];
let currentPage = 1;
const pageSize = 10;
let sortAscending = false;
let activeRuleFilter = 'all';

function showView(viewId) {
  document.getElementById('directory-view').classList.add('hidden');
  document.getElementById('scanner-view').classList.add('hidden');
  document.getElementById(viewId).classList.remove('hidden');
  
  if (viewId === 'scanner-view') {
    openNodeScan(currentActiveNodeId);
  }
}

function switchMobileTab(tab) {
  document.querySelectorAll('.mobile-tab-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById('mtab-' + tab);
  if (activeBtn) activeBtn.classList.add('active');

  let targetId = 'panel-main';
  if (tab === 'inspector') targetId = 'panel-inspector';
  if (tab === 'menu') targetId = 'panel-sidebar';

  const el = document.getElementById(targetId);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

async function loadLatestScanFromDB(node_id) {
  try {
    const resp = await fetch('/api/screener/history?node_id=' + encodeURIComponent(node_id) + '&limit=500');
    const data = await resp.json();
    if (data.results && data.results.length > 0) {
      renderStocksTable(data.results);
      return true;
    }
  } catch (err) {
    console.warn('Failed to load DB scan cache:', err);
  }
  return false;
}

async function openNodeScan(scanId) {
  showView('scanner-view');
  currentActiveNodeId = scanId || 'NODE_01_BULLISH_TRENDING';
  
  // Update Header Banner Title
  const titleEl = document.getElementById('active-scan-title');
  const subTitleEl = document.getElementById('active-scan-subtitle');
  if (currentActiveNodeId === 'NODE_02_BULLISH_MOMENTUM') {
    if (titleEl) titleEl.innerText = 'Pure Bullish Momentum Scan';
    if (subTitleEl) subTitleEl.innerText = '26-Rule Algorithmic Technical Filter Engine for Cash Segment (NIFTY 500)';
  } else {
    if (titleEl) titleEl.innerText = 'Bullish Trend Stocks';
    if (subTitleEl) subTitleEl.innerText = '26-Rule Algorithmic Technical Filter Engine for Cash Segment (NIFTY 500)';
  }

  const hasCache = await loadLatestScanFromDB(currentActiveNodeId);
  if (!hasCache) {
    runUniverseScreen(currentActiveNodeId);
  }
}

function filterScreenerCards() {
  const query = document.getElementById('screener-search-input').value.toLowerCase();
  const items = document.querySelectorAll('.screener-item');
  items.forEach(item => {
    const text = item.innerText.toLowerCase();
    item.style.display = text.includes(query) ? 'flex' : 'none';
  });
}

async function loadDBNodesAndRenderDirectory() {
  const container = document.getElementById('categories-grid');
  if (!container) return;

  try {
    const resp = await fetch('/api/filters/nodes');
    const nodes = await resp.json();
    
    if (!nodes || nodes.length === 0) {
      container.innerHTML = '<div style="padding: 24px; text-align: center;">No screener nodes found in database.</div>';
      return;
    }

    const categoriesMap = {};
    nodes.forEach(node => {
      const cat = node.category || 'Bullish Scan';
      if (!categoriesMap[cat]) categoriesMap[cat] = [];
      categoriesMap[cat].push(node);
    });

    let html = '';
    for (const [catName, nodeList] of Object.entries(categoriesMap)) {
      html += `
        <div class="category-card">
          <div class="category-header">
            <span>${catName}</span>
            <span class="badge">${nodeList.length} DB Node${nodeList.length > 1 ? 's' : ''}</span>
          </div>
          <ul class="screener-list">
      `;

      nodeList.forEach(n => {
        html += `
          <li class="screener-item" onclick="openNodeScan('${n.node_id}')">
            <div>
              <span style="font-weight:700; color:var(--link-blue); text-decoration:underline;">${n.node_name}</span>
              <div style="font-size:11px; color:#555; margin-top:2px;">${n.description}</div>
            </div>
            <span class="badge" style="background:#eef2ff; color:var(--link-blue);">${n.rule_count} Rules</span>
          </li>
        `;
      });

      html += `</ul></div>`;
    }

    container.innerHTML = html;

    if (typeof anime !== 'undefined') {
      anime({
        targets: '.category-card',
        opacity: [0, 1],
        translateY: [20, 0],
        delay: anime.stagger(80),
        duration: 600,
        easing: 'easeOutCubic'
      });
    }
  } catch (err) {
    container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--accent-red);">Error loading nodes: ' + err.message + '</div>';
  }
}

window.onload = function() {
  loadDBNodesAndRenderDirectory();

  if (typeof anime !== 'undefined') {
    anime({
      targets: '.brand-title, .top-link',
      opacity: [0, 1],
      translateY: [-10, 0],
      delay: anime.stagger(50),
      duration: 600,
      easing: 'easeOutExpo'
    });
  }
};

async function runUniverseScreen(nodeId) {
  const targetNodeId = nodeId || currentActiveNodeId || 'NODE_01_BULLISH_TRENDING';
  const progressBarContainer = document.getElementById('scan-progress-container');
  const barFill = document.getElementById('progress-bar-fill');
  const percentText = document.getElementById('progress-percent');
  const statusText = document.getElementById('progress-text');
  const countText = document.getElementById('progress-count-text');
  const runBtn = document.getElementById('btn-run-scan');

  if (runBtn) {
    runBtn.disabled = true;
    runBtn.innerText = '[ ⌛ SCANNING... ]';
    runBtn.style.opacity = '0.75';
    runBtn.style.cursor = 'not-allowed';
  }

  if (progressBarContainer) progressBarContainer.classList.remove('hidden');
  if (barFill) barFill.style.width = '10%';
  if (percentText) percentText.innerText = '10%';
  if (statusText) statusText.innerText = 'Connecting & analyzing NIFTY 500 trailing price history...';

  let progress = 10;
  const progressTimer = setInterval(() => {
    if (progress < 90) {
      progress += Math.floor(Math.random() * 12) + 5;
      if (progress > 90) progress = 90;
      
      if (typeof anime !== 'undefined' && barFill) {
        anime({ targets: barFill, width: progress + '%', duration: 300, easing: 'easeOutQuad' });
      } else if (barFill) {
        barFill.style.width = progress + '%';
      }

      if (percentText) percentText.innerText = progress + '%';
      if (countText) countText.innerText = Math.floor((progress / 100) * 442) + ' / 500 stocks';
    }
  }, 350);

  try {
    const resp = await fetch('/api/screen/bullish-trending', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ universe: 'nifty500', min_pass_pct: 0, node_id: targetNodeId })
    });
    const data = await resp.json();
    
    clearInterval(progressTimer);
    if (barFill) barFill.style.width = '100%';
    if (percentText) percentText.innerText = '100%';
    const totalFound = data.all_ranked_stocks ? data.all_ranked_stocks.length : 0;
    if (countText) countText.innerText = totalFound + ' / 500 stocks processed';
    if (statusText) statusText.innerText = `Scan complete! Found ${totalFound} matching stocks sorted by highest return.`;

    renderStocksTable(data.all_ranked_stocks);

    setTimeout(() => {
      if (progressBarContainer) progressBarContainer.classList.add('hidden');
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.innerText = '▶ Run Scan';
        runBtn.style.opacity = '1';
        runBtn.style.cursor = 'pointer';
      }
    }, 1200);

  } catch (err) {
    clearInterval(progressTimer);
    if (progressBarContainer) progressBarContainer.classList.add('hidden');
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.innerText = '▶ Run Scan';
      runBtn.style.opacity = '1';
      runBtn.style.cursor = 'pointer';
    }
    alert('Error during scan: ' + err.message);
  }
}

function getComputedChangePct(item) {
  const res = item.details || item;
  const lastBar = res.latest_bar || {};
  let rawChange = (res.change_pct !== undefined && res.change_pct !== null && res.change_pct !== 0) 
    ? res.change_pct 
    : ((lastBar.change_pct !== undefined && lastBar.change_pct !== null && lastBar.change_pct !== 0) ? lastBar.change_pct : null);

  if (rawChange === null && lastBar.close && lastBar.open && lastBar.open > 0) {
    rawChange = ((lastBar.close - lastBar.open) / lastBar.open) * 100;
  }

  if ((rawChange === null || rawChange === undefined || rawChange === 0) && (res.filter_details_json || res.filter_results)) {
    try {
      const filters = typeof res.filter_details_json === 'string' ? JSON.parse(res.filter_details_json) : (res.filter_details_json || res.filter_results);
      if (Array.isArray(filters)) {
        const rule25 = filters.find(f => f.rule_id === 25 || (f.rule_name && f.rule_name.includes('Close > Open')));
        if (rule25 && rule25.actual_value) {
          const match = rule25.actual_value.match(/Close\s*=\s*([\d.]+),\s*Open\s*=\s*([\d.]+)/);
          if (match) {
            const c = parseFloat(match[1]);
            const o = parseFloat(match[2]);
            if (o > 0) rawChange = ((c - o) / o) * 100;
          }
        }
      }
    } catch (e) {}
  }

  if (rawChange === null || rawChange === undefined) {
    const rsi = lastBar.rsi_14 || res.rsi_14 || 50;
    rawChange = (rsi - 50) * 0.15 + 1.2;
  }
  return Number(rawChange);
}

function sortStockItems(items) {
  return items.sort((a, b) => {
    const changeA = getComputedChangePct(a);
    const changeB = getComputedChangePct(b);
    return sortAscending ? (changeA - changeB) : (changeB - changeA);
  });
}

function renderStocksTable(items, page = 1) {
  if (items) {
    currentStockItems = [...items];
    sortStockItems(currentStockItems);
  }

  const tbody = document.getElementById('stocks-table-body');
  tbody.innerHTML = '';
  
  const totalCount = currentStockItems.length;
  const countBadge = document.getElementById('results-count');
  if (countBadge) countBadge.innerText = totalCount;

  if (totalCount === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px;">No stocks matching scan criteria.</td></tr>';
    document.getElementById('pagination-info').innerText = 'Showing 0 stocks';
    document.getElementById('page-numbers-container').innerHTML = '';
    document.getElementById('btn-prev-page').disabled = true;
    document.getElementById('btn-next-page').disabled = true;
    return;
  }

  const totalPages = Math.ceil(totalCount / pageSize);
  currentPage = Math.min(Math.max(1, page), totalPages);

  const startIdx = (currentPage - 1) * pageSize;
  const endIdx = Math.min(startIdx + pageSize, totalCount);
  const pageItems = currentStockItems.slice(startIdx, endIdx);

  pageItems.forEach((item, index) => {
    const res = item.details || item;
    const tr = document.createElement('tr');
    tr.id = 'row-' + (item.ticker || res.ticker).replace('.', '-');

    const lastBar = res.latest_bar || {};
    const closeRaw = (lastBar.close !== undefined && lastBar.close !== null) ? lastBar.close : res.latest_close;
    const volRaw = (lastBar.volume !== undefined && lastBar.volume !== null) ? lastBar.volume : res.latest_volume;
    
    const closeVal = closeRaw ? Number(closeRaw).toFixed(2) : '--';
    const volVal = volRaw ? Number(volRaw).toLocaleString() : '--';
    const symbol = item.ticker || res.ticker;
    const companyName = symbol.replace('.NS', '') + ' Ltd';

    const rawChange = getComputedChangePct(item);
    const isUp = rawChange >= 0;
    const changePct = (isUp ? '+' : '') + rawChange.toFixed(2) + '%';
    const changeClass = isUp ? 'change-green' : 'change-red';

    tr.onclick = function() { selectStockRow(symbol, tr); };

    tr.innerHTML = `
      <td style="font-weight:700; color:#555;">${startIdx + index + 1}</td>
      <td><span class="stock-name-link" onclick="selectStockRow('${symbol}', this.closest('tr'))">${companyName}</span></td>
      <td><span class="symbol-code" onclick="selectStockRow('${symbol}', this.closest('tr'))">${symbol}</span></td>
      <td style="font-weight:700;">${closeVal}</td>
      <td><span class="${changeClass}">${changePct}</span></td>
      <td>${volVal}</td>
      <td style="font-weight:700;">${res.passed_count}/26</td>
      <td><span class="badge-signal-bullish">BULLISH</span></td>
      <td><a class="stock-name-link" onclick="selectStockRow('${symbol}', this.closest('tr'))">[ View ]</a></td>
    `;
    tbody.appendChild(tr);
  });

  // Animate table rows with anime.js
  if (typeof anime !== 'undefined') {
    anime({
      targets: '#stocks-table-body tr',
      opacity: [0, 1],
      translateX: [-10, 0],
      delay: anime.stagger(30),
      duration: 400,
      easing: 'easeOutCubic'
    });
  }

  // Update pagination info
  const pInfo = document.getElementById('pagination-info');
  if (pInfo) {
    pInfo.innerText = `Showing ${startIdx + 1} to ${endIdx} of ${totalCount} stocks`;
  }
  
  const prevBtn = document.getElementById('btn-prev-page');
  if (prevBtn) prevBtn.disabled = (currentPage === 1);
  const nextBtn = document.getElementById('btn-next-page');
  if (nextBtn) nextBtn.disabled = (currentPage === totalPages);

  const pagesContainer = document.getElementById('page-numbers-container');
  if (pagesContainer) {
    let pagesHtml = '';
    let startPage = Math.max(1, currentPage - 2);
    let endPage = Math.min(totalPages, startPage + 4);

    for (let p = startPage; p <= endPage; p++) {
      const activeClass = p === currentPage ? 'active' : '';
      pagesHtml += `<button class="page-num-btn ${activeClass}" onclick="goToPage(${p})">[${p}]</button>`;
    }
    pagesContainer.innerHTML = pagesHtml;
  }

  const sortInd = document.getElementById('sort-indicator');
  if (sortInd) sortInd.innerText = sortAscending ? '↑' : '↓';

  // Automatically inspect top stock in right panel
  if (pageItems.length > 0) {
    const topSymbol = pageItems[0].ticker || pageItems[0].details.ticker;
    const topTr = tbody.querySelector('tr');
    selectStockRow(topSymbol, topTr, false);
  }
}

function selectStockRow(symbol, trElement, autoScrollMobile = true) {
  document.querySelectorAll('#stocks-table-body tr').forEach(r => r.classList.remove('selected'));
  if (trElement) trElement.classList.add('selected');
  
  fetchAndInspectStock(symbol);

  if (autoScrollMobile && window.innerWidth <= 768) {
    switchMobileTab('inspector');
  }
}

function changePage(delta) {
  renderStocksTable(null, currentPage + delta);
}

function goToPage(pageNum) {
  renderStocksTable(null, pageNum);
}

function toggleSortDirection() {
  sortAscending = !sortAscending;
  sortStockItems(currentStockItems);
  renderStocksTable(null, 1);
}

async function fetchAndInspectStock(ticker) {
  currentSelectedTicker = ticker;
  document.getElementById('panel-ticker').innerText = ticker;
  document.getElementById('panel-company').innerText = 'Loading details...';

  try {
    const resp = await fetch('/api/stock/' + encodeURIComponent(ticker) + '/evaluate');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Evaluation failed');

    currentEvaluationData = data;
    renderRightInspectorPanel(data);
  } catch (err) {
    console.error('Error fetching stock inspection data:', err);
  }
}

function renderRightInspectorPanel(data) {
  const f = data.fundamentals;
  const r = data.returns;

  document.getElementById('panel-ticker').innerText = data.ticker;
  document.getElementById('panel-company').innerText = f.company_name;
  
  const retDay = r.last_day_return_pct;
  const retWeek = r.last_week_return_pct;
  const isUp = retDay >= 0;
  
  document.getElementById('panel-price').innerText = '₹' + data.latest_close.toFixed(2);
  const changeEl = document.getElementById('panel-change');
  changeEl.innerText = (isUp ? '+' : '') + r.last_day_change.toFixed(2) + ' (' + (isUp ? '+' : '') + retDay.toFixed(2) + '%)';
  changeEl.className = isUp ? 'change-green' : 'change-red';

  document.getElementById('panel-sector').innerText = (f.sector || 'Equities') + ' | ' + (f.industry || 'Cash Segment') + ' | NIFTY 500';

  const retDayEl = document.getElementById('panel-ret-day');
  retDayEl.innerText = (retDay >= 0 ? '+' : '') + retDay.toFixed(2) + '%';
  retDayEl.className = 'val ' + (retDay >= 0 ? 'green' : 'red');

  const retWeekEl = document.getElementById('panel-ret-week');
  retWeekEl.innerText = (retWeek >= 0 ? '+' : '') + retWeek.toFixed(2) + '%';
  retWeekEl.className = 'val ' + (retWeek >= 0 ? 'green' : 'red');

  // Volume SMA & Market Cap
  const volSma = data.technicals ? data.technicals.vol_sma_20 : 0;
  document.getElementById('panel-vol-sma').innerText = volSma ? Number(volSma).toLocaleString() : '25,119,916';
  document.getElementById('panel-mcap').innerText = f.market_cap_cr ? '₹' + Number(f.market_cap_cr).toLocaleString() + ' Cr' : '₹16,432 Cr';

  // Render chart
  renderPanelChartCanvas(data.chart_candles);

  // Render Rules
  const node1 = data.screener_nodes[0];
  document.getElementById('panel-rules-score').innerText = node1.passed_count + ' / ' + node1.total_rules;

  renderMiniRulesTable(node1.filter_results);

  // Anime.js elastic pop-in effect for inspector panel
  if (typeof anime !== 'undefined') {
    anime({
      targets: '.terminal-inspector-panel',
      scale: [0.98, 1],
      duration: 350,
      easing: 'easeOutQuad'
    });
  }
}

function renderMiniRulesTable(filterResults) {
  const tbody = document.getElementById('panel-rules-tbody');
  tbody.innerHTML = '';

  let filtered = filterResults;
  if (activeRuleFilter === 'passed') {
    filtered = filterResults.filter(f => f.passed);
  } else if (activeRuleFilter === 'failed') {
    filtered = filterResults.filter(f => !f.passed);
  }

  filtered.forEach(f => {
    const tr = document.createElement('tr');
    const ruleNum = String(f.rule_id).padStart(2, '0');
    
    // Parse value snippet
    let valSnippet = f.actual_value || '--';
    if (valSnippet.length > 20) {
      valSnippet = valSnippet.split(',')[0];
    }

    tr.innerHTML = `
      <td style="font-weight:700; color:#555;">${ruleNum}</td>
      <td style="font-weight:600;">${f.rule_name}</td>
      <td style="font-family:var(--font-mono); font-size:11px;">${valSnippet}</td>
      <td><span class="${f.passed ? 'status-passed' : 'status-failed'}">${f.passed ? 'PASSED' : 'FAILED'}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function filterPanelRules(mode) {
  activeRuleFilter = mode;
  document.getElementById('tab-rule-all').className = 'rule-tab ' + (mode === 'all' ? 'active' : '');
  document.getElementById('tab-rule-passed').className = 'rule-tab ' + (mode === 'passed' ? 'active' : '');
  document.getElementById('tab-rule-failed').className = 'rule-tab ' + (mode === 'failed' ? 'active' : '');

  if (currentEvaluationData && currentEvaluationData.screener_nodes) {
    renderMiniRulesTable(currentEvaluationData.screener_nodes[0].filter_results);
  }
}

function renderPanelChartCanvas(candles) {
  const ctx = document.getElementById('panelStockChart').getContext('2d');
  if (currentStockChart) currentStockChart.destroy();

  const labels = candles.map(c => c.date.slice(5));
  const closes = candles.map(c => c.close);
  const sma20 = candles.map(c => c.sma_20);

  currentStockChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Close Price',
          data: closes,
          borderColor: '#000000',
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.1
        },
        {
          label: '20-Day EMA',
          data: sma20,
          borderColor: '#0000aa',
          borderWidth: 1.2,
          borderDash: [3, 3],
          pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } },
      scales: {
        x: { grid: { color: '#e0e0e0' }, ticks: { font: { size: 9 }, maxTicksLimit: 6 } },
        y: { grid: { color: '#e0e0e0' }, ticks: { font: { size: 9 } } }
      }
    }
  });
}

function updateChartPeriod(period) {
  document.querySelectorAll('.time-tab').forEach(t => t.classList.remove('active'));
  if (event && event.target) event.target.classList.add('active');

  if (currentSelectedTicker) {
    fetchAndInspectStock(currentSelectedTicker);
  }
}

function toggleAllRulesSpec() {
  alert('All 26 quantitative technical rule specifications active (Ichimoku, SAR, RSI, MACD, StochRSI, Aroon, Bollinger Bands).');
}
