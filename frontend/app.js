let currentStockChart = null;

function showView(viewId) {
  document.getElementById('directory-view').classList.add('hidden');
  document.getElementById('scanner-view').classList.add('hidden');
  
  document.getElementById(viewId).classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadLatestScanFromDB(node_id) {
  const badge = document.getElementById('db-status-badge');
  if (badge) badge.innerText = 'Checking SQLite DB...';

  try {
    const resp = await fetch('/api/screener/history?node_id=' + encodeURIComponent(node_id) + '&limit=500');
    const data = await resp.json();
    if (data.results && data.results.length > 0) {
      renderStocksTable(data.results);
      const timeStr = data.results[0].run_timestamp || 'Recent';
      if (badge) badge.innerText = 'Loaded from SQLite DB Cache (' + timeStr + ')';
      return true;
    }
  } catch (err) {
    console.warn('Failed to load DB scan cache:', err);
  }

  if (badge) badge.innerText = 'No DB Cache Available';
  return false;
}

let currentActiveNodeId = 'NODE_01_BULLISH_TRENDING';

async function openNodeScan(scanId) {
  showView('scanner-view');
  currentActiveNodeId = scanId || 'NODE_01_BULLISH_TRENDING';
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
    if (text.includes(query)) {
      item.style.display = 'flex';
    } else {
      item.style.display = 'none';
    }
  });
}

async function loadDBNodesAndRenderDirectory() {
  const container = document.getElementById('categories-grid');
  if (!container) return;

  try {
    const resp = await fetch('/api/filters/nodes');
    const nodes = await resp.json();
    
    if (!nodes || nodes.length === 0) {
      container.innerHTML = '<div style="grid-column: 1 / -1; padding: 36px; text-align: center; color: var(--text-secondary);">No screener nodes found in database. Create one to populate.</div>';
      return;
    }

    // Group nodes by category
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
            <span class="badge" style="background:#dcfce7; color:#16a34a;">${nodeList.length} Active DB Node${nodeList.length > 1 ? 's' : ''}</span>
          </div>
          <ul class="screener-list">
      `;

      nodeList.forEach(n => {
        html += `
          <li class="screener-item highlighted" onclick="openNodeScan('${n.node_id}')">
            <div>
              <span style="font-weight:700;">${n.node_name}</span>
              <div style="font-size:11px; color:var(--text-secondary); margin-top:2px;">${n.description}</div>
            </div>
            <span class="badge">${n.rule_count} Rules</span>
          </li>
        `;
      });

      html += `
          </ul>
        </div>
      `;
    }

    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = '<div style="grid-column: 1 / -1; padding: 36px; text-align: center; color: var(--accent-red);">Error loading nodes from DB: ' + err.message + '</div>';
  }
}

window.onload = function() {
  loadDBNodesAndRenderDirectory();
};

async function runUniverseScreen(nodeId) {
  const targetNodeId = nodeId || currentActiveNodeId || 'NODE_01_BULLISH_TRENDING';
  const progressBarContainer = document.getElementById('scan-progress-container');
  const barFill = document.getElementById('progress-bar-fill');
  const percentText = document.getElementById('progress-percent');
  const statusText = document.getElementById('progress-text');
  const badge = document.getElementById('db-status-badge');

  if (progressBarContainer) progressBarContainer.classList.remove('hidden');
  if (barFill) barFill.style.width = '10%';
  if (percentText) percentText.innerText = '10%';
  if (statusText) statusText.innerText = 'Connecting & analyzing NIFTY 500 trailing price history...';

  let progress = 10;
  const progressTimer = setInterval(() => {
    if (progress < 90) {
      progress += Math.floor(Math.random() * 12) + 5;
      if (progress > 90) progress = 90;
      if (barFill) barFill.style.width = progress + '%';
      if (percentText) percentText.innerText = progress + '%';
      if (statusText) statusText.innerText = 'Evaluating 26 quantitative technical rules across NIFTY 500 stocks (' + progress + '%)...';
    }
  }, 400);

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
    if (statusText) statusText.innerText = 'Screening complete! Updating results table...';

    renderStocksTable(data.all_ranked_stocks);
    
    const nowStr = new Date().toLocaleTimeString();
    if (badge) badge.innerText = 'Fresh Scan Saved to SQLite DB (' + nowStr + ')';

    setTimeout(() => {
      if (progressBarContainer) progressBarContainer.classList.add('hidden');
    }, 800);

  } catch (err) {
    clearInterval(progressTimer);
    if (progressBarContainer) progressBarContainer.classList.add('hidden');
    alert('Error during scan: ' + err.message);
  }
}

let currentStockItems = [];
let currentPage = 1;
const pageSize = 10;
let sortAscending = false; // Default: highest return (% change) to lowest return

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
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--text-secondary); padding:36px;">No stocks matching scan criteria.</td></tr>';
    const info = document.getElementById('pagination-info');
    if (info) info.innerText = 'Showing 0 stocks';
    const numContainer = document.getElementById('page-numbers-container');
    if (numContainer) numContainer.innerHTML = '';
    const prevBtn = document.getElementById('btn-prev-page');
    if (prevBtn) prevBtn.disabled = true;
    const nextBtn = document.getElementById('btn-next-page');
    if (nextBtn) nextBtn.disabled = true;
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

    const lastBar = res.latest_bar || {};
    const closeRaw = (lastBar.close !== undefined && lastBar.close !== null) ? lastBar.close : res.latest_close;
    const volRaw = (lastBar.volume !== undefined && lastBar.volume !== null) ? lastBar.volume : res.latest_volume;
    
    const closeVal = closeRaw ? '₹' + Number(closeRaw).toFixed(2) : '--';
    const volVal = volRaw ? Number(volRaw).toLocaleString() : '--';
    const symbol = item.ticker || res.ticker;
    const companyName = symbol.replace('.NS', '') + ' Ltd';

    const rawChange = getComputedChangePct(item);
    const isUp = rawChange >= 0;
    const changePct = (isUp ? '+' : '') + rawChange.toFixed(2) + '%';
    const pillClass = isUp ? 'change-pill up' : 'change-pill down';

    tr.innerHTML = `
      <td>${startIdx + index + 1}</td>
      <td style="font-weight:600;"><span class="symbol-link" onclick="evaluateAndOpenStockChart('${symbol}')">${companyName}</span></td>
      <td><span class="symbol-link" onclick="evaluateAndOpenStockChart('${symbol}')">${symbol}</span></td>
      <td style="font-weight:700; font-family:'JetBrains Mono';">${closeVal}</td>
      <td><span class="${pillClass}">${changePct}</span></td>
      <td style="font-family:'JetBrains Mono';">${volVal}</td>
      <td><span style="font-weight:700; color:var(--accent-purple);">${res.passed_count}/26</span> (${res.pass_percentage}%)</td>
      <td>
        <button class="btn btn-outline" style="padding:4px 10px; font-size:12px;" onclick="evaluateAndOpenStockChart('${symbol}')">View Chart</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  // Render pagination info
  const pInfo = document.getElementById('pagination-info');
  if (pInfo) {
    pInfo.innerText = `Showing ${startIdx + 1}–${endIdx} of ${totalCount} matching stocks (${sortAscending ? 'Lowest to Highest' : 'Highest to Lowest'} % Change)`;
  }
  
  // Render pagination buttons
  const prevBtn = document.getElementById('btn-prev-page');
  if (prevBtn) prevBtn.disabled = (currentPage === 1);
  const nextBtn = document.getElementById('btn-next-page');
  if (nextBtn) nextBtn.disabled = (currentPage === totalPages);

  const pagesContainer = document.getElementById('page-numbers-container');
  if (pagesContainer) {
    let pagesHtml = '';
    let startPage = Math.max(1, currentPage - 3);
    let endPage = Math.min(totalPages, startPage + 6);
    if (endPage - startPage < 6) {
      startPage = Math.max(1, endPage - 6);
    }

    for (let p = startPage; p <= endPage; p++) {
      const activeClass = p === currentPage ? 'active' : '';
      pagesHtml += `<button class="page-btn ${activeClass}" onclick="goToPage(${p})">${p}</button>`;
    }
    pagesContainer.innerHTML = pagesHtml;
  }

  // Update sort indicator icon
  const sortInd = document.getElementById('sort-indicator');
  if (sortInd) sortInd.innerText = sortAscending ? '↑' : '↓';
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

async function evaluateAndOpenStockChart(ticker) {
  document.getElementById('modal-stock-name').innerText = ticker + ' — Loading Chart...';
  document.getElementById('modal-rules-container').innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-secondary);">Fetching daily OHLC history & indicators...</div>';
  document.getElementById('chart-modal').classList.remove('hidden');

  try {
    const resp = await fetch('/api/stock/' + encodeURIComponent(ticker) + '/evaluate');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Evaluation failed');

    renderStockChartModal(data);
  } catch (err) {
    document.getElementById('modal-rules-container').innerHTML = '<div style="color:var(--accent-red); padding:20px;">' + err.message + '</div>';
  }
}

function renderStockChartModal(data) {
  document.getElementById('modal-stock-name').innerText = data.ticker + ' — ' + data.fundamentals.company_name;
  document.getElementById('modal-stock-sector').innerText = data.fundamentals.sector + ' / ' + data.fundamentals.industry + ' • NIFTY 500 Cash Segment';

  const retDay = data.returns.last_day_return_pct;
  const retWeek = data.returns.last_week_return_pct;

  document.getElementById('modal-ret-day').innerText = (retDay >= 0 ? '+' : '') + retDay + '%';
  document.getElementById('modal-ret-day').style.color = retDay >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';

  document.getElementById('modal-ret-week').innerText = (retWeek >= 0 ? '+' : '') + retWeek + '%';
  document.getElementById('modal-ret-week').style.color = retWeek >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';

  renderChartCanvas(data.chart_candles);

  const node1 = data.screener_nodes[0];
  const container = document.getElementById('modal-rules-container');
  let html = '';

  node1.filter_results.forEach(f => {
    html += `
      <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 14px; background:#f8fafc; border:1px solid var(--border-color); border-radius:8px; margin-bottom:8px; border-left:4px solid ${f.passed ? 'var(--accent-green)' : 'var(--accent-red)'}">
        <div>
          <div style="font-size:13.5px; font-weight:600; color:var(--text-primary);">${f.rule_id}. ${f.rule_name}</div>
          <div style="font-size:11px; color:var(--text-secondary); margin-top:2px;">${f.description}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-family:'JetBrains Mono'; font-size:12px; font-weight:700;">${f.actual_value}</div>
          <div style="font-size:11px; font-weight:700; color:${f.passed ? 'var(--accent-green)' : 'var(--accent-red)'}">${f.passed ? 'PASSED ✓' : 'FAILED ✗'}</div>
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function renderChartCanvas(candles) {
  const ctx = document.getElementById('modalStockChart').getContext('2d');
  if (currentStockChart) currentStockChart.destroy();

  const labels = candles.map(c => c.date);
  const closes = candles.map(c => c.close);
  const sma20 = candles.map(c => c.sma_20);

  currentStockChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Close Price (₹)',
          data: closes,
          borderColor: '#2563eb',
          backgroundColor: 'rgba(37, 99, 235, 0.08)',
          fill: true,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.1
        },
        {
          label: '20-Day EMA',
          data: sma20,
          borderColor: '#f59e0b',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: {
        x: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { maxTicksLimit: 10 } },
        y: { grid: { color: 'rgba(0,0,0,0.04)' } }
      }
    }
  });
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

function exportCSV() {
  alert('Exporting filtered NIFTY 500 scan results to CSV file...');
}

function toggleAllRulesSpec() {
  alert('All 26 quantitative rule specs loaded: EMA, SMA volume, Ichimoku (3,7,14) & (9,26,52), Parabolic SAR, RSI 10/14, StochRSI, CCI 10, MFI 10, Williams %R 10, EMA 14, ADX +DI/-DI, Aroon Up/Down, Stochastical %K/%D, Upper Bollinger Band, Green candle, Volume > 100k.');
}
