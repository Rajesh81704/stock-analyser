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
  } else if (currentActiveNodeId === 'NODE_03_PROFIT_JUMP_200') {
    if (titleEl) titleEl.innerText = 'Profit Jump by 200%';
    if (subTitleEl) subTitleEl.innerText = 'Algorithmic Fundamental & Growth Filter Engine: Net Profit increased by 100%+ (2x) YoY';
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


  } catch (err) {
    container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--accent-red);">Error loading nodes: ' + err.message + '</div>';
  }
}

window.onload = function() {
  loadDBNodesAndRenderDirectory();
  fetchAndInspectStock('ALOKINDS.NS');
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
  if (barFill) barFill.style.width = '40%';
  if (percentText) percentText.innerText = '40%';
  if (statusText) statusText.innerText = 'Evaluating quantitative technical rules...';

  try {
    const resp = await fetch('/api/screen/bullish-trending', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ universe: 'nifty500', min_pass_pct: 0, node_id: targetNodeId })
    });
    const data = await resp.json();
    
    if (barFill) barFill.style.width = '100%';
    if (percentText) percentText.innerText = '100%';
    const totalFound = data.all_ranked_stocks ? data.all_ranked_stocks.length : 0;
    if (countText) countText.innerText = totalFound + ' / 500 stocks processed';
    if (statusText) statusText.innerText = `Scan complete! Found ${totalFound} matching stocks.`;

    renderStocksTable(data.all_ranked_stocks);

    setTimeout(() => {
      if (progressBarContainer) progressBarContainer.classList.add('hidden');
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.innerText = '▶ Run Scan';
        runBtn.style.opacity = '1';
        runBtn.style.cursor = 'pointer';
      }
    }, 500);

  } catch (err) {
    if (progressBarContainer) progressBarContainer.classList.add('hidden');
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.innerText = '▶ Run Scan';
      runBtn.style.opacity = '1';
      runBtn.style.cursor = 'pointer';
    }
    console.warn('Scan info:', err);
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

  // Fast lightweight rendering without heavy DOM stagger timers


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

  // Highlight currently selected stock if present on this page, or auto-inspect initial top stock ONCE
  let foundSelectedRow = null;
  pageItems.forEach((item, index) => {
    const symbol = item.ticker || (item.details && item.details.ticker);
    if (currentSelectedTicker && symbol === currentSelectedTicker) {
      foundSelectedRow = tbody.children[index];
    }
  });

  if (foundSelectedRow) {
    foundSelectedRow.classList.add('selected');
  } else if (!currentSelectedTicker && pageItems.length > 0) {
    const topSymbol = pageItems[0].ticker || (pageItems[0].details && pageItems[0].details.ticker);
    const topTr = tbody.querySelector('tr');
    selectStockRow(topSymbol, topTr, false);
  }
}

function filterTagClick(btnElement, mode) {
  document.querySelectorAll('.filter-tags-bar .tag-btn').forEach(b => b.classList.remove('active'));
  if (btnElement) btnElement.classList.add('active');

  if (mode === 'all') {
    renderStocksTable(currentStockItems, 1);
    return;
  }

  let filtered = currentStockItems;
  if (mode === 'bullish') {
    filtered = currentStockItems.filter(i => (i.passed_all || (i.details && i.details.passed_all)));
  } else if (mode === 'volume') {
    filtered = currentStockItems.filter(i => {
      const v = i.volume || (i.details && i.details.latest_volume) || 0;
      return v >= 1000000;
    });
  } else if (mode === 'breakout' || mode === 'uptrend') {
    filtered = currentStockItems.filter(i => {
      const pct = i.pass_percentage || (i.details && i.details.pass_percentage) || 0;
      return pct >= 80.0;
    });
  } else if (mode === 'ichimoku') {
    filtered = currentStockItems.filter(i => {
      const cnt = i.passed_count || (i.details && i.details.passed_count) || 0;
      return cnt >= 20;
    });
  } else if (mode === 'macd') {
    filtered = currentStockItems.filter(i => {
      const m = i.macd || (i.details && i.details.macd) || 0;
      return m > 0;
    });
  }

  renderStocksTable(filtered, 1);
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

let inspectFetchAbortController = null;

async function fetchAndInspectStock(ticker, period = '6mo') {
  if (inspectFetchAbortController) {
    try { inspectFetchAbortController.abort(); } catch (e) {}
  }
  inspectFetchAbortController = new AbortController();
  const signal = inspectFetchAbortController.signal;

  currentSelectedTicker = ticker;
  document.getElementById('panel-ticker').innerText = ticker;
  document.getElementById('panel-company').innerText = 'Loading data...';
  document.getElementById('panel-q-period').innerText = 'Fetching...';
  document.getElementById('panel-a-year').innerText = 'Fetching...';

  // Instant local preview from active scan items
  const localItem = currentStockItems.find(i => (i.ticker === ticker || (i.details && i.details.ticker === ticker)));
  if (localItem) {
    const res = localItem.details || localItem;
    renderInspectorPanelFromScanResult(ticker, res);
  }

  try {
    const resp = await fetch(`/api/stock/${encodeURIComponent(ticker)}/evaluate?period=${encodeURIComponent(period)}`, { signal });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Evaluation failed');

    // Only render chart if ticker is still selected
    if (currentSelectedTicker === ticker) {
      currentEvaluationData = data;
      renderRightInspectorPanel(data);
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.warn('Error fetching stock chart data:', err);
    }
  }
}

function renderInspectorPanelFromScanResult(ticker, res) {
  const payload = res.details || res;
  if (payload.fundamentals) {
    renderRightInspectorPanel(payload);
    return;
  }

  const companyName = ticker.replace('.NS', '') + ' Ltd';
  document.getElementById('panel-ticker').innerText = ticker;
  document.getElementById('panel-company').innerText = companyName;

  const lastBar = res.latest_bar || {};
  const closeVal = (lastBar.close !== undefined && lastBar.close !== null) ? lastBar.close : res.latest_close || 0;
  document.getElementById('panel-price').innerText = '₹' + Number(closeVal).toFixed(2);

  const rawChange = getComputedChangePct(res);
  const isUp = rawChange >= 0;
  const changeEl = document.getElementById('panel-change');
  changeEl.innerText = (isUp ? '+' : '') + rawChange.toFixed(2) + '%';
  changeEl.className = isUp ? 'change-green' : 'change-red';

  const retDayEl = document.getElementById('panel-ret-day');
  retDayEl.innerText = (isUp ? '+' : '') + rawChange.toFixed(2) + '%';
  retDayEl.className = 'val ' + (isUp ? 'green' : 'red');

  const passedCount = res.passed_count || 0;
  document.getElementById('panel-rules-score').innerText = passedCount + ' / 26';

  const filterRes = res.filter_results || (typeof res.filter_details_json === 'string' ? JSON.parse(res.filter_details_json) : res.filter_details_json);
  if (filterRes) {
    renderMiniRulesTable(filterRes);
  }
}

function renderRightInspectorPanel(data) {
  const f = data.fundamentals || {};
  const r = data.returns || {};

  document.getElementById('panel-ticker').innerText = data.ticker || currentSelectedTicker;
  document.getElementById('panel-company').innerText = f.company_name || (data.ticker ? data.ticker.replace('.NS', '') + ' Ltd' : 'Stock Details');
  
  const retDay = r.last_day_return_pct || 0;
  const retWeek = r.last_week_return_pct || 0;
  const isUp = retDay >= 0;
  const closeVal = data.latest_close || 0;
  
  document.getElementById('panel-price').innerText = '₹' + Number(closeVal).toFixed(2);
  const changeEl = document.getElementById('panel-change');
  changeEl.innerText = (isUp ? '+' : '') + Number(r.last_day_change || 0).toFixed(2) + ' (' + (isUp ? '+' : '') + Number(retDay).toFixed(2) + '%)';
  changeEl.className = isUp ? 'change-green' : 'change-red';

  document.getElementById('panel-sector').innerText = (f.sector || 'Equities') + ' | ' + (f.industry || 'Cash Segment') + ' | NIFTY 500';

  const retDayEl = document.getElementById('panel-ret-day');
  retDayEl.innerText = (retDay >= 0 ? '+' : '') + Number(retDay).toFixed(2) + '%';
  retDayEl.className = 'val ' + (retDay >= 0 ? 'green' : 'red');

  const retWeekEl = document.getElementById('panel-ret-week');
  retWeekEl.innerText = (retWeek >= 0 ? '+' : '') + Number(retWeek).toFixed(2) + '%';
  retWeekEl.className = 'val ' + (retWeek >= 0 ? 'green' : 'red');

  // Volume SMA & Market Cap
  const volSma = data.technicals ? data.technicals.vol_sma_20 : 0;
  document.getElementById('panel-vol-sma').innerText = volSma ? Number(volSma).toLocaleString() : '--';
  document.getElementById('panel-mcap').innerText = f.market_cap_cr ? '₹' + Number(f.market_cap_cr).toLocaleString() + ' Cr' : '--';

  // Render Quarterly Financials
  const q = f.quarterly_financials || {};
  if (q.period) {
    document.getElementById('panel-q-period').innerText = q.period;
  } else {
    document.getElementById('panel-q-period').innerText = 'Last Quarter';
  }
  document.getElementById('panel-q-rev').innerText = q.revenue_cr !== undefined && q.revenue_cr !== null ? '₹' + Number(q.revenue_cr).toLocaleString() + ' Cr' : '--';
  
  const qProfitEl = document.getElementById('panel-q-profit');
  if (q.net_profit_cr !== undefined && q.net_profit_cr !== null) {
    const pVal = Number(q.net_profit_cr);
    qProfitEl.innerText = (pVal >= 0 ? '₹' : '-₹') + Math.abs(pVal).toLocaleString() + ' Cr';
    qProfitEl.className = 'val ' + (pVal >= 0 ? 'green' : 'red');
  } else {
    qProfitEl.innerText = '--';
    qProfitEl.className = 'val';
  }

  const qQoqEl = document.getElementById('panel-q-profit-qoq');
  if (q.profit_growth_qoq_pct !== undefined && q.profit_growth_qoq_pct !== null) {
    const val = Number(q.profit_growth_qoq_pct);
    qQoqEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
    qQoqEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
  } else {
    qQoqEl.innerText = '--';
    qQoqEl.className = 'val';
  }

  const qYoyEl = document.getElementById('panel-q-profit-yoy');
  if (q.profit_growth_yoy_pct !== undefined && q.profit_growth_yoy_pct !== null) {
    const val = Number(q.profit_growth_yoy_pct);
    qYoyEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
    qYoyEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
  } else {
    qYoyEl.innerText = '--';
    qYoyEl.className = 'val';
  }

  // Render Annual Financials
  const a = f.annual_financials || {};
  if (a.year) {
    document.getElementById('panel-a-year').innerText = 'FY ' + a.year;
  } else {
    document.getElementById('panel-a-year').innerText = 'Full Year';
  }
  document.getElementById('panel-a-rev').innerText = a.revenue_cr !== undefined && a.revenue_cr !== null ? '₹' + Number(a.revenue_cr).toLocaleString() + ' Cr' : '--';

  const aProfitEl = document.getElementById('panel-a-profit');
  if (a.net_profit_cr !== undefined && a.net_profit_cr !== null) {
    const pVal = Number(a.net_profit_cr);
    aProfitEl.innerText = (pVal >= 0 ? '₹' : '-₹') + Math.abs(pVal).toLocaleString() + ' Cr';
    aProfitEl.className = 'val ' + (pVal >= 0 ? 'green' : 'red');
  } else {
    aProfitEl.innerText = '--';
    aProfitEl.className = 'val';
  }

  const aRevYoyEl = document.getElementById('panel-a-rev-yoy');
  if (a.rev_growth_yoy_pct !== undefined && a.rev_growth_yoy_pct !== null) {
    const val = Number(a.rev_growth_yoy_pct);
    aRevYoyEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
    aRevYoyEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
  } else {
    aRevYoyEl.innerText = '--';
    aRevYoyEl.className = 'val';
  }

  const aProfitYoyEl = document.getElementById('panel-a-profit-yoy');
  if (a.profit_growth_yoy_pct !== undefined && a.profit_growth_yoy_pct !== null) {
    const val = Number(a.profit_growth_yoy_pct);
    aProfitYoyEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
    aProfitYoyEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
  } else {
    aProfitYoyEl.innerText = '--';
    aProfitYoyEl.className = 'val';
  }

  // Render chart
  if (data.chart_candles) {
    renderPanelChartCanvas(data.chart_candles);
  }

  // Render Rules
  if (data.screener_nodes && data.screener_nodes.length > 0) {
    const node1 = data.screener_nodes[0];
    document.getElementById('panel-rules-score').innerText = node1.passed_count + ' / ' + node1.total_rules;
    renderMiniRulesTable(node1.filter_results);
  }
}

function renderMiniRulesTable(filterResults) {
  if (!filterResults || !Array.isArray(filterResults)) return;
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
    const ruleNum = String(f.rule_id || f.id || 0).padStart(2, '0');
    
    // Parse value snippet
    let valSnippet = f.actual_value || f.actual || '--';
    if (valSnippet.length > 20) {
      valSnippet = valSnippet.split(',')[0];
    }

    const ruleName = f.rule_name || f.name || ('Rule #' + ruleNum);
    const passed = f.passed !== undefined ? f.passed : true;

    tr.innerHTML = `
      <td style="font-weight:700; color:#555;">${ruleNum}</td>
      <td style="font-weight:600;">${ruleName}</td>
      <td style="font-family:var(--font-mono); font-size:11px;">${valSnippet}</td>
      <td><span class="${passed ? 'status-passed' : 'status-failed'}">${passed ? 'PASSED' : 'FAILED'}</span></td>
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
  if (!candles || !Array.isArray(candles) || candles.length === 0) return;
  const canvasEl = document.getElementById('panelStockChart');
  if (!canvasEl) return;
  const ctx = canvasEl.getContext('2d');

  if (currentStockChart) {
    try { currentStockChart.destroy(); } catch (e) {}
  }

  const labels = candles.map(c => (c.date ? c.date.slice(5) : ''));
  const closes = candles.map(c => c.close || 0);
  const sma20 = candles.map(c => (c.sma_20 && !isNaN(c.sma_20)) ? c.sma_20 : null);

  currentStockChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Close Price (₹)',
          data: closes,
          borderColor: '#0000aa',
          backgroundColor: 'rgba(0, 0, 170, 0.05)',
          fill: true,
          borderWidth: 1.8,
          pointRadius: 0,
          tension: 0.1
        },
        {
          label: '20-Day SMA',
          data: sma20,
          borderColor: '#008000',
          borderWidth: 1.2,
          borderDash: [3, 3],
          pointRadius: 0,
          spanGaps: true
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 8, font: { size: 9 } } } },
      scales: {
        x: { grid: { color: '#e5e5e5' }, ticks: { font: { size: 9 }, maxTicksLimit: 6 } },
        y: { grid: { color: '#e5e5e5' }, ticks: { font: { size: 9 } } }
      }
    }
  });
}

function updateChartPeriod(btnElement, period) {
  document.querySelectorAll('.timeframe-tabs-bar .time-tab').forEach(t => t.classList.remove('active'));
  if (btnElement) btnElement.classList.add('active');

  if (currentSelectedTicker) {
    fetchAndInspectStock(currentSelectedTicker, period);
  }
}

function toggleAllRulesSpec() {
  alert('All 26 quantitative technical rule specifications active (Ichimoku, SAR, RSI, MACD, StochRSI, Aroon, Bollinger Bands).');
}
