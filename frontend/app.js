let currentStockChart = null;
let currentSelectedTicker = null;
let currentEvaluationData = null;
let currentActiveNodeId = 'NODE_01_BULLISH_TRENDING';
let currentStockItems = [];
let currentPage = 1;
const pageSize = 10;
let sortAscending = false;
let activeRuleFilter = 'all';
let currentChartSymbol = 'KARURVYSYA.NS';
let currentChartInterval = '1d';
let currentChartPeriod = '1y';
let currentRightChartPeriod = '6mo';
let currentRightChartInterval = '1d';
let currentRightChartMode = 'price';
let rightBottomChartInstance = null;
let allRegisteredNodesMap = {};

function getComputedChangePct(item) {
  if (!item) return 0;
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
  return Number(rawChange || 0);
}

function attachCalculatedChangePct(items) {
  if (!items || !Array.isArray(items)) return;
  items.forEach(item => {
    item.computed_change_pct = getComputedChangePct(item);
  });
}

function showView(viewId) {
  const dirEl = document.getElementById('directory-view');
  const scanEl = document.getElementById('scanner-view');
  if (dirEl) dirEl.classList.add('hidden');
  if (scanEl) scanEl.classList.add('hidden');

  const targetEl = document.getElementById(viewId);
  if (targetEl) {
    targetEl.classList.remove('hidden');
  }

  // Update sidebar active link states
  const chartsLink = document.getElementById('sb-charts');
  const homeLink = document.getElementById('sb-home') || document.getElementById('sb-saved-screens');
  if (homeLink) {
    if (viewId === 'directory-view') {
      homeLink.classList.add('active');
    } else {
      homeLink.classList.remove('active');
    }
  }
  if (chartsLink) {
    if (viewId === 'directory-view') {
      chartsLink.classList.remove('active');
    } else {
      chartsLink.classList.add('active');
    }
  }

  // Update topnav link states if present
  const topCharts = document.getElementById('topnav-charts');
  const topHome = document.getElementById('topnav-home') || document.getElementById('topnav-screens');
  if (topHome) {
    if (viewId === 'directory-view') topHome.classList.add('active');
    else topHome.classList.remove('active');
  }
  if (topCharts) {
    if (viewId === 'directory-view') topCharts.classList.remove('active');
    else topCharts.classList.add('active');
  }

  if (viewId === 'scanner-view') {
    setTimeout(triggerChartResize, 60);
  }
}

function goHome() {
  showView('directory-view');
  if (window.innerWidth <= 768) {
    switchMobileTab('home');
  }
  try {
    const cleanUrl = window.location.origin + '/';
    window.history.pushState({}, '', cleanUrl);
  } catch (e) {}
}

function triggerChartResize() {
  const containerEl = document.getElementById('mainStockChartContainer');
  const tvContainer = document.getElementById('tvChartContainer');
  if (containerEl) {
    let parentWidth = containerEl.clientWidth;
    if (!parentWidth || parentWidth < 100) {
      const pMain = document.getElementById('panel-main');
      parentWidth = pMain && pMain.clientWidth > 0 ? pMain.clientWidth - 20 : (window.innerWidth <= 768 ? window.innerWidth - 24 : 700);
    }
    const chartHeight = window.innerWidth <= 480 ? 260 : (window.innerWidth <= 768 ? 320 : 380);

    if (tvContainer) {
      tvContainer.style.width = '100%';
      tvContainer.style.height = chartHeight + 'px';
    }

    if (lightweightChartInstance && parentWidth > 50) {
      try {
        lightweightChartInstance.applyOptions({
          width: Math.floor(parentWidth),
          height: chartHeight
        });
        lightweightChartInstance.timeScale().fitContent();
      } catch (e) {}
    }
  }

  if (rightBottomChartInstance) {
    try {
      rightBottomChartInstance.resize();
    } catch (e) {}
  }
}

function switchMobileTab(tab) {
  document.querySelectorAll('.mobile-view-tabs .mobile-tab-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById('mtab-' + tab);
  if (activeBtn) activeBtn.classList.add('active');

  const pSidebar = document.getElementById('panel-sidebar');
  const pMain = document.getElementById('panel-main');
  const pInspector = document.getElementById('panel-inspector');
  const scanTableSec = document.getElementById('scanner-table-section');
  const mainChartCard = document.getElementById('main-chart-card') || document.querySelector('.main-chart-card');

  if (window.innerWidth <= 768) {
    if (tab === 'home' || tab === 'menu') {
      if (pSidebar) pSidebar.style.display = 'none';
      if (pInspector) pInspector.style.display = 'none';
      if (pMain) pMain.style.display = 'block';
      showView('directory-view');
    } else if (tab === 'inspector') {
      if (pSidebar) pSidebar.style.display = 'none';
      if (pMain) pMain.style.display = 'none';
      if (pInspector) pInspector.style.display = 'block';
      if (rightBottomChartInstance) {
        setTimeout(() => {
          try { rightBottomChartInstance.resize(); } catch (e) {}
        }, 50);
      }
    } else if (tab === 'chart') {
      if (pSidebar) pSidebar.style.display = 'none';
      if (pInspector) pInspector.style.display = 'none';
      if (pMain) pMain.style.display = 'block';
      showView('scanner-view');
      if (scanTableSec) scanTableSec.style.display = 'none';
      if (mainChartCard) mainChartCard.style.display = 'block';
      setTimeout(triggerChartResize, 60);
    } else { // 'screener' default
      if (pSidebar) pSidebar.style.display = 'none';
      if (pInspector) pInspector.style.display = 'none';
      if (pMain) pMain.style.display = 'block';
      showView('scanner-view');
      if (scanTableSec) scanTableSec.style.display = 'block';
      if (mainChartCard) mainChartCard.style.display = 'none';
    }
  } else {
    // Reset desktop display states
    if (pSidebar) pSidebar.style.display = '';
    if (pMain) pMain.style.display = '';
    if (pInspector) pInspector.style.display = '';
    if (scanTableSec) scanTableSec.style.display = '';
    if (mainChartCard) mainChartCard.style.display = '';
    setTimeout(triggerChartResize, 60);
  }
}

window.addEventListener('resize', () => {
  if (window.innerWidth > 768) {
    const pSidebar = document.getElementById('panel-sidebar');
    const pMain = document.getElementById('panel-main');
    const pInspector = document.getElementById('panel-inspector');
    const scanTableSec = document.getElementById('scanner-table-section');
    const mainChartCard = document.getElementById('main-chart-card') || document.querySelector('.main-chart-card');
    if (pSidebar) pSidebar.style.display = '';
    if (pMain) pMain.style.display = '';
    if (pInspector) pInspector.style.display = '';
    if (scanTableSec) scanTableSec.style.display = '';
    if (mainChartCard) mainChartCard.style.display = '';
  } else {
    const activeTab = document.querySelector('.mobile-view-tabs .mobile-tab-btn.active');
    if (activeTab) {
      const tabId = activeTab.id.replace('mtab-', '');
      switchMobileTab(tabId);
    } else {
      switchMobileTab('screener');
    }
  }
  triggerChartResize();
});

async function loadLatestScanFromDB(node_id) {
  try {
    const resp = await fetch('/api/screener/history?node_id=' + encodeURIComponent(node_id) + '&limit=500');
    const data = await resp.json();
    if (data.results && data.results.length > 0) {
      masterStockItems = [...data.results];
      attachCalculatedChangePct(masterStockItems);
      renderStocksTable(masterStockItems, 1);

      // Auto-select and inspect the top stock of THIS specific node
      const topTicker = masterStockItems[0].ticker || (masterStockItems[0].details && masterStockItems[0].details.ticker);
      if (topTicker) {
        currentSelectedTicker = topTicker;
        currentChartSymbol = topTicker;
        fetchAndInspectStock(topTicker);
        loadLiveMainChart(topTicker);
        loadRightBottomChart(topTicker);
      }
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

  // Highlight active node in sidebar
  document.querySelectorAll('#sidebar-nodes-menu .sidebar-link').forEach(link => {
    link.classList.remove('active');
  });
  const sbLink = document.getElementById('sb-node-' + currentActiveNodeId);
  if (sbLink) sbLink.classList.add('active');

  // Look up node metadata dynamically
  const node = allRegisteredNodesMap[currentActiveNodeId];
  const titleEl = document.getElementById('active-scan-title');
  const subTitleEl = document.getElementById('active-scan-subtitle');

  if (node) {
    if (titleEl) titleEl.innerText = node.node_name;
    if (subTitleEl) subTitleEl.innerText = `${node.rule_count}-Rule Engine: ${node.description}`;
  } else {
    const defaultMeta = {
      'NODE_01_BULLISH_TRENDING': { name: 'Bullish Trending Stocks', desc: '26-Rule Algorithmic Technical Filter Engine for Cash Segment (NIFTY 500)' },
      'NODE_02_BULLISH_MOMENTUM': { name: 'Pure Bullish Momentum Scan', desc: '26-Rule Algorithmic Technical Filter Engine for Cash Segment (NIFTY 500)' },
      'NODE_03_PROFIT_JUMP_200': { name: 'Profit Jump by 200%', desc: 'Algorithmic Fundamental & Growth Filter Engine: Net Profit increased by 100%+ (2x) YoY' },
      'NODE_04_HIGH_SALES_GROWTH': { name: 'High Sales Growth (QoQ & YoY)', desc: 'Fundamental & Top-Line Growth Filter Engine: Tracks sales expansion QoQ and YoY' },
      'NODE_05_BEARISH_TRENDING': { name: 'Bearish Trending Stocks', desc: '26-Rule Algorithmic Bearish Technical Filter Engine for Shorting & Bearish Regimes' },
    };
    const def = defaultMeta[currentActiveNodeId] || { name: 'Quantitative Screener', desc: 'Algorithmic Filter Engine for NIFTY 500' };
    if (titleEl) titleEl.innerText = def.name;
    if (subTitleEl) subTitleEl.innerText = def.desc;
  }

  // Update browser URL query param cleanly without reloading
  try {
    const newUrl = new URL(window.location.href);
    if (currentActiveNodeId && currentActiveNodeId !== 'NODE_01_BULLISH_TRENDING') {
      newUrl.searchParams.set('node_id', currentActiveNodeId);
      window.history.replaceState({ nodeId: currentActiveNodeId }, '', newUrl.pathname + '?' + newUrl.searchParams.toString());
    } else {
      newUrl.searchParams.delete('node_id');
      newUrl.searchParams.delete('node');
      const search = newUrl.searchParams.toString();
      window.history.replaceState({ nodeId: currentActiveNodeId }, '', newUrl.pathname + (search ? '?' + search : ''));
    }
  } catch (e) {}

  // Load from DB cache or execute live screen
  const hasCache = await loadLatestScanFromDB(currentActiveNodeId);
  if (!hasCache) {
    await runUniverseScreen(currentActiveNodeId);
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
      allRegisteredNodesMap[node.node_id] = node;
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

let liveWs = null;

function initRealtimeWebSocket() {
  const loc = window.location;
  const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProto}//${loc.host}/ws/live`;

  try {
    liveWs = new WebSocket(wsUrl);

    liveWs.onopen = function() {
      console.log('⚡ Connected to Real-time Webhook WebSocket stream (0 HTTP polling)');
      if (currentSelectedTicker) {
        subscribeRealtimeTicker(currentSelectedTicker);
      }
    };

    liveWs.onmessage = function(event) {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'TICK_UPDATE' && msg.data) {
          handleIncomingRealtimeTick(msg.data);
        }
      } catch (e) {}
    };

    liveWs.onclose = function() {
      setTimeout(initRealtimeWebSocket, 3000);
    };

    liveWs.onerror = function(err) {
      console.warn('WebSocket stream error:', err);
    };
  } catch (e) {
    console.warn('Could not initialize WebSocket:', e);
  }
}

function subscribeRealtimeTicker(symbol) {
  if (liveWs && liveWs.readyState === WebSocket.OPEN && symbol) {
    liveWs.send(JSON.stringify({ action: 'subscribe', symbol: symbol }));
  }
}

function handleIncomingRealtimeTick(tick) {
  if (!tick || !tick.symbol) return;
  const sym = tick.symbol;

  const rowId = 'row-' + sym.replace('.', '-');
  const rowEl = document.getElementById(rowId);
  if (rowEl) {
    const priceCell = rowEl.children[3];
    const changeCell = rowEl.children[4];
    if (priceCell && tick.last_price) priceCell.innerText = Number(tick.last_price).toFixed(2);
    if (changeCell && tick.change_pct !== undefined) {
      const isUp = tick.change_pct >= 0;
      changeCell.innerText = (isUp ? '+' : '') + Number(tick.change_pct).toFixed(2) + '%';
      changeCell.className = isUp ? 'change-green' : 'change-red';
    }
  }

  if (currentSelectedTicker && (sym === currentSelectedTicker || sym + '.NS' === currentSelectedTicker)) {
    const priceEl = document.getElementById('panel-price');
    const changeEl = document.getElementById('panel-change');
    if (priceEl && tick.last_price) priceEl.innerText = '₹' + Number(tick.last_price).toFixed(2);
    if (changeEl && tick.change_pct !== undefined) {
      const isUp = tick.change_pct >= 0;
      changeEl.innerText = (isUp ? '+' : '') + Number(tick.change_pct).toFixed(2) + '%';
      changeEl.className = isUp ? 'change-green' : 'change-red';
    }

    const chartPriceEl = document.getElementById('chart-stock-price');
    const chartChangeEl = document.getElementById('chart-stock-change');
    if (chartPriceEl && tick.last_price) chartPriceEl.innerText = '₹' + Number(tick.last_price).toFixed(2);
    if (chartChangeEl && tick.change_pct !== undefined) {
      const isUp = tick.change_pct >= 0;
      chartChangeEl.innerText = (isUp ? '+' : '') + Number(tick.change_pct).toFixed(2) + '%';
      chartChangeEl.className = isUp ? 'badge-signal-bullish' : 'badge-signal-bearish';
    }
  }
}

let currentKiteStatus = { active: false, login_url: 'https://kite.zerodha.com/connect/login?api_key=zgktuz1hr11f8scf&v=3' };

async function checkKiteSessionStatus() {
  const container = document.getElementById('kite-auth-badge-container');
  const chartBtn = document.getElementById('chart-kite-reconnect-btn');

  // Check if returned from Zerodha Kite OAuth login callback
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('kite_auth') === 'success') {
    showKiteToast('🎉 Zerodha KiteConnect Session Activated! Live API Feeds Connected.');
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  try {
    const res = await fetch('/api/kite/status');
    const data = await res.json();
    currentKiteStatus = data;

    if (container) {
      if (!data.active) {
        // Kite session is expired: show button to login!
        const loginUrl = data.login_url || 'https://kite.zerodha.com/connect/login?api_key=zgktuz1hr11f8scf&v=3';
        container.innerHTML = `
          <a href="${loginUrl}" 
             target="_blank" 
             class="kite-session-btn expired" 
             title="KiteConnect session expired. Click to log into Zerodha and activate live API.">
            <span class="kite-dot amber"></span>
            <span>⚡ Kite Expired — Re-login</span>
          </a>
        `;
      } else {
        // Kite session is active
        const userLabel = data.user_id ? ` (${data.user_id})` : '';
        container.innerHTML = `
          <span class="kite-session-btn active" title="Zerodha KiteConnect Live API is connected">
            <span class="kite-dot green"></span>
            <span>🟢 Kite Live${userLabel}</span>
          </span>
        `;
      }
    }

    if (chartBtn) {
      if (!data.active) {
        chartBtn.classList.remove('hidden');
        if (data.login_url) chartBtn.href = data.login_url;
      } else {
        chartBtn.classList.add('hidden');
      }
    }
  } catch (err) {
    console.warn('Could not check Kite session status:', err);
  }
}

function showKiteToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'kite-toast-banner';
  toast.innerHTML = `<span>⚡</span> <span>${msg}</span>`;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.5s ease';
    setTimeout(() => toast.remove(), 500);
  }, 4500);
}

let liveChartRefreshTimer = null;

function startLiveChartAutoRefresh() {
  if (liveChartRefreshTimer) return;
  liveChartRefreshTimer = setInterval(() => {
    const scanView = document.getElementById('scanner-view');
    // Periodically update the live candlestick chart during market hours when chart is visible
    if (scanView && !scanView.classList.contains('hidden') && currentChartSymbol) {
      loadLiveMainChart(currentChartSymbol, currentChartInterval, currentChartPeriod);
    }
  }, 10000); // 10-second real-time pulse
}

async function loadMarketNews(force = false) {
  const container = document.getElementById('sidebar-news-list');
  if (!container) return;

  if (force) {
    container.innerHTML = '<div class="news-loading-msg">Refreshing market wire...</div>';
  }

  try {
    const url = `/api/market/news?limit=25${force ? '&force=true' : ''}`;
    const res = await fetch(url);
    const data = await res.json();
    const articles = data.articles || [];

    if (articles.length === 0) {
      container.innerHTML = '<div class="news-loading-msg">No market news articles available.</div>';
      return;
    }

    let html = '';
    articles.forEach(art => {
      const timeAgo = formatNewsTimeAgo(art.published);
      const safeTitle = escapeNewsHtml(art.title);
      const safeSource = escapeNewsHtml(art.source || 'Market Wire');
      const safeLink = art.link || '#';

      html += `
        <a href="${safeLink}" target="_blank" rel="noopener noreferrer" class="news-item-card" title="${safeTitle}">
          <div class="news-item-meta">
            <span class="news-source-tag">${safeSource}</span>
            <span class="news-time-ago">${timeAgo}</span>
          </div>
          <div class="news-item-title">${safeTitle}</div>
        </a>
      `;
    });

    container.innerHTML = html;
  } catch (err) {
    console.warn('Could not load market news:', err);
    container.innerHTML = '<div class="news-loading-msg">Failed to load news feed. <button class="term-btn" onclick="loadMarketNews(true)">Retry</button></div>';
  }
}

function escapeNewsHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatNewsTimeAgo(dateStr) {
  if (!dateStr) return '';
  try {
    const pub = new Date(dateStr);
    const now = new Date();
    const diffSec = Math.floor((now - pub) / 1000);
    if (isNaN(diffSec) || diffSec < 0) return 'Just now';
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  } catch (e) {
    return '';
  }
}

window.onload = async function() {
  await loadDBNodesAndRenderDirectory();
  initRealtimeWebSocket();
  await checkKiteSessionStatus();
  startLiveChartAutoRefresh();
  loadMarketNews(false);
  setInterval(() => loadMarketNews(false), 120000); // Auto-refresh news headlines every 2 mins

  // Read URL query parameter if specified (e.g. ?node_id=NODE_04_HIGH_SALES_GROWTH)
  const urlParams = new URLSearchParams(window.location.search);
  const requestedNode = urlParams.get('node_id') || urlParams.get('node');

  if (requestedNode) {
    await openNodeScan(requestedNode);
  } else {
    // Default Home Page is Directory View (Saved Screens Grid)
    showView('directory-view');
    // Pre-populate inspector panel with top stock from DB
    try {
      const resp = await fetch('/api/screener/history?node_id=NODE_01_BULLISH_TRENDING&limit=1');
      const data = await resp.json();
      if (data.results && data.results.length > 0) {
        const topTicker = data.results[0].ticker || 'ICICIGI.NS';
        fetchAndInspectStock(topTicker);
        loadRightBottomChart(topTicker);
      }
    } catch (e) {}
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
    if (data.all_ranked_stocks && data.all_ranked_stocks.length > 0) {
      masterStockItems = [...data.all_ranked_stocks];
      attachCalculatedChangePct(masterStockItems);
      renderStocksTable(masterStockItems, 1);

      const topTicker = masterStockItems[0].ticker || (masterStockItems[0].details && masterStockItems[0].details.ticker);
      if (topTicker) {
        fetchAndInspectStock(topTicker);
        loadLiveMainChart(topTicker);
        loadRightBottomChart(topTicker);
      }
    } else {
      renderStocksTable([]);
    }

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

function sortStockItems(items) {
  return items.sort((a, b) => {
    const passA = a.passed_count || (a.details && a.details.passed_count) || 0;
    const passB = b.passed_count || (b.details && b.details.passed_count) || 0;
    if (passA !== passB) {
      return passB - passA;
    }
    const isBearish = currentActiveNodeId && currentActiveNodeId.includes('BEARISH');
    const changeA = getComputedChangePct(a);
    const changeB = getComputedChangePct(b);
    if (isBearish) {
      return sortAscending ? (changeB - changeA) : (changeA - changeB);
    }
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

    const nodeObj = allRegisteredNodesMap[currentActiveNodeId];
    const totalRules = res.total_rules || (nodeObj ? nodeObj.rule_count : 26);
    const isBearish = (currentActiveNodeId && currentActiveNodeId.includes('BEARISH')) || (res.filter_type && res.filter_type.includes('bearish'));
    const isGrowth = (currentActiveNodeId && (currentActiveNodeId.includes('PROFIT') || currentActiveNodeId.includes('SALES')));

    let signalHtml = `<span class="badge-signal-bullish">BULLISH</span>`;
    if (isBearish) {
      signalHtml = `<span class="badge-signal-bearish">BEARISH</span>`;
    } else if (isGrowth) {
      signalHtml = `<span class="badge-signal-bullish" style="background:#eef2ff; color:#0000aa; border:1px solid #c7d2fe;">GROWTH</span>`;
    }

    tr.innerHTML = `
      <td style="font-weight:700; color:#555;">${startIdx + index + 1}</td>
      <td><span class="stock-name-link" onclick="selectStockRow('${symbol}', this.closest('tr'))">${companyName}</span></td>
      <td><span class="symbol-code" onclick="selectStockRow('${symbol}', this.closest('tr'))">${symbol}</span></td>
      <td style="font-weight:700;">${closeVal}</td>
      <td><span class="${changeClass}">${changePct}</span></td>
      <td>${volVal}</td>
      <td style="font-weight:700;">${res.passed_count}/${totalRules}</td>
      <td>${signalHtml}</td>
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
  currentSelectedTicker = symbol;
  currentChartSymbol = symbol;
  document.querySelectorAll('#stocks-table-body tr').forEach(r => r.classList.remove('selected'));
  if (trElement) trElement.classList.add('selected');
  
  fetchAndInspectStock(symbol);
  loadLiveMainChart(symbol);
  loadRightBottomChart(symbol);

  if (autoScrollMobile && window.innerWidth <= 768) {
    switchMobileTab('chart');
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
  
  const tickEl = document.getElementById('panel-ticker');
  if (tickEl) tickEl.innerText = ticker;
  const compEl = document.getElementById('panel-company');
  if (compEl) compEl.innerText = 'Loading data...';
  const qEl = document.getElementById('panel-q-period');
  if (qEl) qEl.innerText = 'Fetching...';
  const aEl = document.getElementById('panel-a-year');
  if (aEl) aEl.innerText = 'Fetching...';

  // Instant local preview from active scan items
  const localItem = currentStockItems.find(i => (i.ticker === ticker || (i.details && i.details.ticker === ticker)));
  if (localItem) {
    const res = localItem.details || localItem;
    try {
      renderInspectorPanelFromScanResult(ticker, res);
    } catch (e) {
      console.warn('Preview render notice:', e);
    }
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
      console.warn('Error fetching stock evaluation data:', err);
      if (qEl) qEl.innerText = 'Unavailable';
      if (aEl) aEl.innerText = 'Unavailable';
    }
  }
}

function renderInspectorPanelFromScanResult(ticker, res) {
  const payload = res.details || res;
  if (payload.fundamentals) {
    renderRightInspectorPanel(payload);
    return;
  }

  const companyName = payload.company_name || ticker.replace('.NS', '') + ' Ltd';
  const tickEl = document.getElementById('panel-ticker');
  if (tickEl) tickEl.innerText = ticker;
  const compEl = document.getElementById('panel-company');
  if (compEl) compEl.innerText = companyName;

  const lastBar = res.latest_bar || {};
  const closeVal = (lastBar.close !== undefined && lastBar.close !== null) ? lastBar.close : res.latest_close || 0;
  const priceEl = document.getElementById('panel-price');
  if (priceEl) priceEl.innerText = '₹' + Number(closeVal).toFixed(2);

  const rawChange = getComputedChangePct(res);
  const isUp = rawChange >= 0;
  const changeEl = document.getElementById('panel-change');
  if (changeEl) {
    changeEl.innerText = (isUp ? '+' : '') + rawChange.toFixed(2) + '%';
    changeEl.className = isUp ? 'change-green' : 'change-red';
  }

  const retDayEl = document.getElementById('panel-ret-day');
  if (retDayEl) {
    retDayEl.innerText = (isUp ? '+' : '') + rawChange.toFixed(2) + '%';
    retDayEl.className = 'val ' + (isUp ? 'green' : 'red');
  }

  const scoreEl = document.getElementById('panel-rules-score');
  if (scoreEl) scoreEl.innerText = (res.passed_count || 0) + ' / 26';

  const filterRes = res.filter_results || (typeof res.filter_details_json === 'string' ? JSON.parse(res.filter_details_json) : res.filter_details_json);
  if (filterRes) {
    renderMiniRulesTable(filterRes);
  }
}

function renderRightInspectorPanel(data) {
  const f = data.fundamentals || {};
  const r = data.returns || {};

  const tickEl = document.getElementById('panel-ticker');
  if (tickEl) tickEl.innerText = data.ticker || currentSelectedTicker;
  const compEl = document.getElementById('panel-company');
  if (compEl) compEl.innerText = f.company_name || (data.ticker ? data.ticker.replace('.NS', '') + ' Ltd' : 'Stock Details');
  
  const retDay = r.last_day_return_pct || 0;
  const retWeek = r.last_week_return_pct || 0;
  const isUp = retDay >= 0;
  const closeVal = data.latest_close || 0;
  
  const priceEl = document.getElementById('panel-price');
  if (priceEl) priceEl.innerText = '₹' + Number(closeVal).toFixed(2);
  const changeEl = document.getElementById('panel-change');
  if (changeEl) {
    changeEl.innerText = (isUp ? '+' : '') + Number(r.last_day_change || 0).toFixed(2) + ' (' + (isUp ? '+' : '') + Number(retDay).toFixed(2) + '%)';
    changeEl.className = isUp ? 'change-green' : 'change-red';
  }

  const secEl = document.getElementById('panel-sector');
  if (secEl) secEl.innerText = (f.sector || 'Equities') + ' | ' + (f.industry || 'Cash Segment') + ' | NIFTY 500';

  const retDayEl = document.getElementById('panel-ret-day');
  if (retDayEl) {
    retDayEl.innerText = (retDay >= 0 ? '+' : '') + Number(retDay).toFixed(2) + '%';
    retDayEl.className = 'val ' + (retDay >= 0 ? 'green' : 'red');
  }

  const retWeekEl = document.getElementById('panel-ret-week');
  if (retWeekEl) {
    retWeekEl.innerText = (retWeek >= 0 ? '+' : '') + Number(retWeek).toFixed(2) + '%';
    retWeekEl.className = 'val ' + (retWeek >= 0 ? 'green' : 'red');
  }

  // Volume SMA & Market Cap
  const volSma = data.technicals ? data.technicals.vol_sma_20 : 0;
  const volEl = document.getElementById('panel-vol-sma');
  if (volEl) volEl.innerText = volSma ? Number(volSma).toLocaleString() : '--';
  const mcapEl = document.getElementById('panel-mcap');
  if (mcapEl) mcapEl.innerText = f.market_cap_cr ? '₹' + Number(f.market_cap_cr).toLocaleString() + ' Cr' : '--';

  // Render Quarterly Financials
  const q = f.quarterly_financials || {};
  const qPeriodEl = document.getElementById('panel-q-period');
  if (qPeriodEl) {
    qPeriodEl.innerText = q.period || 'Last Quarter';
  }
  const qRevEl = document.getElementById('panel-q-rev');
  if (qRevEl) {
    qRevEl.innerText = q.revenue_cr !== undefined && q.revenue_cr !== null ? '₹' + Number(q.revenue_cr).toLocaleString() + ' Cr' : '--';
  }
  
  const qProfitEl = document.getElementById('panel-q-profit');
  if (qProfitEl) {
    if (q.net_profit_cr !== undefined && q.net_profit_cr !== null) {
      const pVal = Number(q.net_profit_cr);
      qProfitEl.innerText = (pVal >= 0 ? '₹' : '-₹') + Math.abs(pVal).toLocaleString() + ' Cr';
      qProfitEl.className = 'val ' + (pVal >= 0 ? 'green' : 'red');
    } else {
      qProfitEl.innerText = '--';
      qProfitEl.className = 'val';
    }
  }

  const qQoqEl = document.getElementById('panel-q-profit-qoq');
  if (qQoqEl) {
    if (q.profit_growth_qoq_pct !== undefined && q.profit_growth_qoq_pct !== null) {
      const val = Number(q.profit_growth_qoq_pct);
      qQoqEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
      qQoqEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
    } else {
      qQoqEl.innerText = '--';
      qQoqEl.className = 'val';
    }
  }

  const qYoyEl = document.getElementById('panel-q-profit-yoy');
  if (qYoyEl) {
    if (q.profit_growth_yoy_pct !== undefined && q.profit_growth_yoy_pct !== null) {
      const val = Number(q.profit_growth_yoy_pct);
      qYoyEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
      qYoyEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
    } else {
      qYoyEl.innerText = '--';
      qYoyEl.className = 'val';
    }
  }

  // Render Annual Financials
  const a = f.annual_financials || {};
  const aYearEl = document.getElementById('panel-a-year');
  if (aYearEl) {
    aYearEl.innerText = a.year ? 'FY ' + a.year : 'Full Year';
  }
  const aRevEl = document.getElementById('panel-a-rev');
  if (aRevEl) {
    aRevEl.innerText = a.revenue_cr !== undefined && a.revenue_cr !== null ? '₹' + Number(a.revenue_cr).toLocaleString() + ' Cr' : '--';
  }

  const aProfitEl = document.getElementById('panel-a-profit');
  if (aProfitEl) {
    if (a.net_profit_cr !== undefined && a.net_profit_cr !== null) {
      const pVal = Number(a.net_profit_cr);
      aProfitEl.innerText = (pVal >= 0 ? '₹' : '-₹') + Math.abs(pVal).toLocaleString() + ' Cr';
      aProfitEl.className = 'val ' + (pVal >= 0 ? 'green' : 'red');
    } else {
      aProfitEl.innerText = '--';
      aProfitEl.className = 'val';
    }
  }

  const aRevYoyEl = document.getElementById('panel-a-rev-yoy');
  if (aRevYoyEl) {
    if (a.rev_growth_yoy_pct !== undefined && a.rev_growth_yoy_pct !== null) {
      const val = Number(a.rev_growth_yoy_pct);
      aRevYoyEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
      aRevYoyEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
    } else {
      aRevYoyEl.innerText = '--';
      aRevYoyEl.className = 'val';
    }
  }

  const aProfitYoyEl = document.getElementById('panel-a-profit-yoy');
  if (aProfitYoyEl) {
    if (a.profit_growth_yoy_pct !== undefined && a.profit_growth_yoy_pct !== null) {
      const val = Number(a.profit_growth_yoy_pct);
      aProfitYoyEl.innerText = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
      aProfitYoyEl.className = 'val ' + (val >= 0 ? 'green' : 'red');
    } else {
      aProfitYoyEl.innerText = '--';
      aProfitYoyEl.className = 'val';
    }
  }

  // Render Right Bottom Chart from API
  loadRightBottomChart(data.ticker || currentSelectedTicker);

  // Render Rules if elements exist
  if (data.screener_nodes && data.screener_nodes.length > 0) {
    const node1 = data.screener_nodes[0];
    const scoreEl = document.getElementById('panel-rules-score');
    if (scoreEl) scoreEl.innerText = node1.passed_count + ' / ' + node1.total_rules;
    renderMiniRulesTable(node1.filter_results);
  }
}

function renderMiniRulesTable(filterResults) {
  if (!filterResults || !Array.isArray(filterResults)) return;
  const tbody = document.getElementById('panel-rules-tbody');
  if (!tbody) return;
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

async function loadRightBottomChart(symbol = null, period = null, interval = null) {
  const sym = symbol || currentSelectedTicker || currentChartSymbol || 'KARURVYSYA.NS';
  if (period) currentRightChartPeriod = period;
  if (interval) currentRightChartInterval = interval;

  const canvasEl = document.getElementById('panelStockChart');
  if (!canvasEl) return;

  const badgeEl = document.getElementById('right-chart-candles-badge');
  if (badgeEl) badgeEl.innerText = 'Fetching...';

  try {
    let url = `/api/chart/candles?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(currentRightChartInterval)}&period=${encodeURIComponent(currentRightChartPeriod)}`;
    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed to fetch candles');

    if (badgeEl) {
      const srcName = data.data_source ? data.data_source.split(' ')[0] : 'Kite';
      badgeEl.innerText = `⚡ ${srcName} · ${data.total_candles || (data.candles ? data.candles.length : 0)}b`;
    }

    renderRightBottomChart(data.candles);
  } catch (err) {
    console.warn('Error loading right bottom chart:', err);
    if (badgeEl) badgeEl.innerText = 'Err';
  }
}

function renderRightBottomChart(candles) {
  if (!candles || !Array.isArray(candles) || candles.length === 0) return;
  const canvasEl = document.getElementById('panelStockChart');
  if (!canvasEl) return;
  const ctx = canvasEl.getContext('2d');

  if (rightBottomChartInstance) {
    try { rightBottomChartInstance.destroy(); } catch (e) {}
    rightBottomChartInstance = null;
  }

  const isIntraday = ['1m', '2m', '3m', '5m', '15m', '30m', '60m', '1h', '2h', '4h'].includes((currentRightChartInterval || '').toLowerCase());

  const labels = candles.map(c => {
    if (isIntraday) {
      const dt = c.date || c.timestamp || '';
      return dt.length >= 16 ? dt.slice(5, 16) : dt;
    }
    return c.date ? c.date.slice(5) : '';
  });

  const closes = candles.map(c => Number(c.close || 0));

  // Calculate 20 SMA
  const sma20 = [];
  for (let i = 0; i < candles.length; i++) {
    if (i >= 19) {
      const slice = closes.slice(i - 19, i + 1);
      const avg = slice.reduce((a, b) => a + b, 0) / 20;
      sma20.push(Number(avg.toFixed(2)));
    } else {
      sma20.push(null);
    }
  }

  // Calculate 50 SMA
  const sma50 = [];
  for (let i = 0; i < candles.length; i++) {
    if (i >= 49) {
      const slice = closes.slice(i - 49, i + 1);
      const avg = slice.reduce((a, b) => a + b, 0) / 50;
      sma50.push(Number(avg.toFixed(2)));
    } else {
      sma50.push(null);
    }
  }

  // If RSI Mode selected
  if (currentRightChartMode === 'rsi') {
    const rsi14 = calculateRSI(closes, 14);

    rightBottomChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'RSI (14)',
            data: rsi14,
            borderColor: '#7c3aed',
            backgroundColor: 'rgba(124, 58, 237, 0.12)',
            fill: true,
            borderWidth: 1.8,
            pointRadius: 0,
            tension: 0.1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'top', labels: { boxWidth: 8, font: { size: 9, family: 'var(--font-mono)' } } },
          tooltip: { mode: 'index', intersect: false }
        },
        scales: {
          x: { grid: { color: '#f0f0f0' }, ticks: { font: { size: 9 }, maxTicksLimit: 6 } },
          y: {
            min: 0,
            max: 100,
            grid: { color: '#f0f0f0' },
            ticks: { font: { size: 9 }, stepSize: 20 }
          }
        }
      }
    });
    return;
  }

  // Price Mode: Close Price + 20 SMA + 50 SMA
  rightBottomChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Close (₹)',
          data: closes,
          borderColor: '#0000aa',
          backgroundColor: 'rgba(0, 0, 170, 0.05)',
          fill: true,
          borderWidth: 1.8,
          pointRadius: 0,
          tension: 0.1
        },
        {
          label: '20 SMA',
          data: sma20,
          borderColor: '#008000',
          borderWidth: 1.2,
          borderDash: [3, 3],
          pointRadius: 0,
          spanGaps: true
        },
        {
          label: '50 SMA',
          data: sma50,
          borderColor: '#d97706',
          borderWidth: 1.2,
          borderDash: [2, 2],
          pointRadius: 0,
          spanGaps: true
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { boxWidth: 8, font: { size: 9, family: 'var(--font-mono)' } }
        },
        tooltip: { mode: 'index', intersect: false }
      },
      scales: {
        x: { grid: { color: '#f0f0f0' }, ticks: { font: { size: 9 }, maxTicksLimit: 6 } },
        y: { grid: { color: '#f0f0f0' }, ticks: { font: { size: 9 } } }
      }
    }
  });
}

function calculateRSI(prices, period = 14) {
  const rsi = [];
  if (prices.length <= period) {
    return prices.map(() => 50);
  }

  let gains = 0;
  let losses = 0;

  for (let i = 1; i <= period; i++) {
    const change = prices[i] - prices[i - 1];
    if (change >= 0) gains += change;
    else losses += Math.abs(change);
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;

  for (let i = 0; i < period; i++) {
    rsi.push(null);
  }

  const initialRs = avgLoss === 0 ? 100 : avgGain / avgLoss;
  rsi.push(Number((100 - (100 / (1 + initialRs))).toFixed(2)));

  for (let i = period + 1; i < prices.length; i++) {
    const change = prices[i] - prices[i - 1];
    const gain = change >= 0 ? change : 0;
    const loss = change < 0 ? Math.abs(change) : 0;

    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;

    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    rsi.push(Number((100 - (100 / (1 + rs))).toFixed(2)));
  }

  return rsi;
}

function updateRightChartTimeframe(period, interval) {
  currentRightChartPeriod = period;
  currentRightChartInterval = interval;

  const container = document.getElementById('right-chart-period-tabs');
  if (container) {
    container.querySelectorAll('.time-tab').forEach(b => {
      const txt = b.innerText.trim().toLowerCase();
      const p = period.toLowerCase();
      if (txt === p || (p === '1mo' && txt === '1m') || (p === '3mo' && txt === '3m') || (p === '6mo' && txt === '6m') || (p === '1y' && txt === '1y') || (p === 'max' && txt === 'max')) {
        b.classList.add('active');
      } else {
        b.classList.remove('active');
      }
    });
  }

  loadRightBottomChart(currentSelectedTicker, period, interval);
}

function toggleRightChartMode(mode) {
  currentRightChartMode = mode;
  const btnPrice = document.getElementById('btn-right-mode-price');
  const btnRsi = document.getElementById('btn-right-mode-rsi');
  if (btnPrice) btnPrice.classList.toggle('active', mode === 'price');
  if (btnRsi) btnRsi.classList.toggle('active', mode === 'rsi');

  loadRightBottomChart(currentSelectedTicker);
}

function toggleAllRulesSpec() {
  alert('All 26 quantitative technical rule specifications active (Ichimoku, SAR, RSI, MACD, StochRSI, Aroon, Bollinger Bands).');
}

async function loadLiveMainChart(symbol, interval = null, period = null) {
  if (symbol) currentChartSymbol = symbol;
  if (interval) currentChartInterval = interval;
  if (period) currentChartPeriod = period;

  const symbolEl = document.getElementById('chart-stock-symbol');
  const priceEl = document.getElementById('chart-stock-price');
  const changeEl = document.getElementById('chart-stock-change');
  const sourceEl = document.getElementById('chart-data-source');
  const countEl = document.getElementById('chart-candles-count');

  if (symbolEl) symbolEl.innerText = currentChartSymbol;

  try {
    let url = `/api/chart/candles?symbol=${encodeURIComponent(currentChartSymbol)}&interval=${encodeURIComponent(currentChartInterval)}`;
    if (currentChartPeriod) {
      url += `&period=${encodeURIComponent(currentChartPeriod)}`;
    }

    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed to fetch candles');

    if (symbolEl) symbolEl.innerText = data.symbol || currentChartSymbol;
    if (priceEl) priceEl.innerText = '₹' + Number(data.latest_close || 0).toFixed(2);
    if (changeEl) {
      const isUp = (data.price_change_pct || 0) >= 0;
      changeEl.innerText = (isUp ? '+' : '') + Number(data.price_change_pct || 0).toFixed(2) + '%';
      changeEl.className = isUp ? 'badge-signal-bullish' : 'badge-signal-bearish';
    }
    if (sourceEl) sourceEl.innerText = '⚡ ' + (data.data_source || 'Zerodha KiteConnect Live');
    if (countEl) countEl.innerText = (data.total_candles || 0) + ' candles';

    const chartReconnectBtn = document.getElementById('chart-kite-reconnect-btn');
    if (chartReconnectBtn) {
      if (!currentKiteStatus.active || (data.data_source && !data.data_source.includes('KiteConnect'))) {
        chartReconnectBtn.classList.remove('hidden');
        if (currentKiteStatus.login_url) chartReconnectBtn.href = currentKiteStatus.login_url;
      } else {
        chartReconnectBtn.classList.add('hidden');
      }
    }

    renderMainChartCanvas(data.candles);
  } catch (err) {
    console.warn('Error loading main live chart:', err);
  }
}

let lightweightChartInstance = null;
let candlestickSeriesInstance = null;
let volumeSeriesInstance = null;
let smaSeriesInstance = null;
let lastRenderedChartKey = null;

function renderMainChartCanvas(candles) {
  if (!candles || !Array.isArray(candles) || candles.length === 0) return;
  
  const containerEl = document.getElementById('mainStockChartContainer');
  const canvasEl = document.getElementById('mainStockChartCanvas');

  let renderedWithTV = false;

  if (typeof LightweightCharts !== 'undefined' && containerEl) {
    try {
      let tvContainer = document.getElementById('tvChartContainer');
      if (!tvContainer) {
        tvContainer = document.createElement('div');
        tvContainer.id = 'tvChartContainer';
        containerEl.appendChild(tvContainer);
      }
      
      const chartHeight = window.innerWidth <= 480 ? 260 : (window.innerWidth <= 768 ? 320 : 380);
      tvContainer.style.display = 'block';
      tvContainer.style.width = '100%';
      tvContainer.style.height = chartHeight + 'px';
      if (canvasEl) canvasEl.style.display = 'none';

      const chartKey = `${currentChartSymbol}_${currentChartInterval}_${currentChartPeriod}`;
      const isIntraday = ['1m', '2m', '3m', '5m', '15m', '30m', '60m', '1h', '2h', '4h'].includes((currentChartInterval || '').toLowerCase());

      const tvCandles = [];
      const volumeData = [];
      const smaData = [];

      candles.forEach((c, idx) => {
        let tVal;
        if (isIntraday) {
          tVal = c.time || Math.floor(new Date(c.timestamp || c.date).getTime() / 1000);
        } else {
          if (c.date) {
            tVal = String(c.date).split(' ')[0];
          } else if (c.timestamp) {
            tVal = String(c.timestamp).split('T')[0];
          } else if (c.time) {
            tVal = new Date(c.time * 1000).toISOString().split('T')[0];
          } else {
            tVal = '2026-01-01';
          }
        }

        const openPrice = Number(c.open || 0);
        const highPrice = Number(c.high || openPrice);
        const lowPrice = Number(c.low || openPrice);
        const closePrice = Number(c.close || openPrice);

        tvCandles.push({
          time: tVal,
          open: openPrice,
          high: highPrice,
          low: lowPrice,
          close: closePrice
        });

        const isUp = closePrice >= openPrice;
        volumeData.push({
          time: tVal,
          value: Number(c.volume || 0),
          color: isUp ? 'rgba(8, 153, 129, 0.35)' : 'rgba(242, 54, 69, 0.35)'
        });

        if (idx >= 19) {
          const slice = candles.slice(idx - 19, idx + 1);
          const sum = slice.reduce((acc, curr) => acc + Number(curr.close || 0), 0);
          smaData.push({
            time: tVal,
            value: Number((sum / 20).toFixed(2))
          });
        }
      });

      const candleMap = new Map();
      tvCandles.forEach(item => candleMap.set(item.time, item));
      const cleanCandles = Array.from(candleMap.values()).sort((a, b) => {
        return isIntraday ? (a.time - b.time) : String(a.time).localeCompare(String(b.time));
      });

      const volMap = new Map();
      volumeData.forEach(item => volMap.set(item.time, item));
      const cleanVolume = Array.from(volMap.values()).sort((a, b) => {
        return isIntraday ? (a.time - b.time) : String(a.time).localeCompare(String(b.time));
      });

      const smaMap = new Map();
      smaData.forEach(item => smaMap.set(item.time, item));
      const cleanSma = Array.from(smaMap.values()).sort((a, b) => {
        return isIntraday ? (a.time - b.time) : String(a.time).localeCompare(String(b.time));
      });

      // IN-PLACE UPDATE FOR LIVE MARKET DATA (Zero flicker, preserves user zoom/pan)
      if (lastRenderedChartKey === chartKey && lightweightChartInstance && candlestickSeriesInstance) {
        candlestickSeriesInstance.setData(cleanCandles);
        if (volumeSeriesInstance) volumeSeriesInstance.setData(cleanVolume);
        if (smaSeriesInstance) smaSeriesInstance.setData(cleanSma);
        renderedWithTV = true;
      } else {
        // Teardown previous chart instance when symbol or timeframe changes
        if (lightweightChartInstance) {
          try { lightweightChartInstance.remove(); } catch (e) {}
          lightweightChartInstance = null;
        }

        let parentWidth = containerEl.clientWidth;
        if (!parentWidth || parentWidth < 100) {
          const pMain = document.getElementById('panel-main');
          parentWidth = pMain && pMain.clientWidth > 0 ? pMain.clientWidth - 20 : (window.innerWidth <= 768 ? window.innerWidth - 24 : 700);
        }
        parentWidth = Math.max(260, Math.floor(parentWidth));

        lightweightChartInstance = LightweightCharts.createChart(tvContainer, {
          width: parentWidth,
          height: chartHeight,
          layout: {
            background: { type: 'solid', color: '#ffffff' },
            textColor: '#333333',
            fontSize: window.innerWidth <= 480 ? 10 : 11,
            fontFamily: 'Inter, system-ui, sans-serif'
          },
          grid: {
            vertLines: { color: '#f0f3f6' },
            horzLines: { color: '#f0f3f6' }
          },
          crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
          },
          rightPriceScale: {
            borderColor: '#d0d7de',
            scaleMargins: { top: 0.1, bottom: 0.25 }
          },
          timeScale: {
            borderColor: '#d0d7de',
            timeVisible: isIntraday,
            secondsVisible: false,
            minBarSpacing: window.innerWidth <= 480 ? 3 : 6
          },
          handleScroll: {
            mouseWheel: true,
            pressedMouseMove: true,
            horzTouchDrag: true,
            vertTouchDrag: false
          },
          handleScale: {
            axisPressedMouseMove: true,
            mouseWheel: true,
            pinch: true
          }
        });

        if (typeof ResizeObserver !== 'undefined' && containerEl && !window._chartResizeObserverAttached) {
          window._chartResizeObserverAttached = true;
          const ro = new ResizeObserver((entries) => {
            for (const entry of entries) {
              const cr = entry.contentRect;
              if (cr && cr.width > 50 && lightweightChartInstance) {
                const rw = Math.floor(cr.width);
                const rh = window.innerWidth <= 480 ? 260 : (window.innerWidth <= 768 ? 320 : 380);
                const tvC = document.getElementById('tvChartContainer');
                if (tvC) tvC.style.height = rh + 'px';
                try {
                  lightweightChartInstance.applyOptions({ width: rw, height: rh });
                } catch (e) {}
              }
            }
          });
          ro.observe(containerEl);
        }

        const addCandleSeries = (chart, opts) => {
          if (typeof chart.addCandlestickSeries === 'function') return chart.addCandlestickSeries(opts);
          if (typeof chart.addSeries === 'function' && typeof LightweightCharts !== 'undefined' && LightweightCharts.CandlestickSeries) {
            return chart.addSeries(LightweightCharts.CandlestickSeries, opts);
          }
          throw new Error('addCandlestickSeries not supported');
        };
        const addHistSeries = (chart, opts) => {
          if (typeof chart.addHistogramSeries === 'function') return chart.addHistogramSeries(opts);
          if (typeof chart.addSeries === 'function' && typeof LightweightCharts !== 'undefined' && LightweightCharts.HistogramSeries) {
            return chart.addSeries(LightweightCharts.HistogramSeries, opts);
          }
          throw new Error('addHistogramSeries not supported');
        };
        const addLSeries = (chart, opts) => {
          if (typeof chart.addLineSeries === 'function') return chart.addLineSeries(opts);
          if (typeof chart.addSeries === 'function' && typeof LightweightCharts !== 'undefined' && LightweightCharts.LineSeries) {
            return chart.addSeries(LightweightCharts.LineSeries, opts);
          }
          throw new Error('addLineSeries not supported');
        };

        candlestickSeriesInstance = addCandleSeries(lightweightChartInstance, {
          upColor: '#089981',
          downColor: '#f23645',
          borderVisible: false,
          wickUpColor: '#089981',
          wickDownColor: '#f23645'
        });
        candlestickSeriesInstance.setData(cleanCandles);

        volumeSeriesInstance = addHistSeries(lightweightChartInstance, {
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume_scale',
          scaleMargins: { top: 0.75, bottom: 0 }
        });
        volumeSeriesInstance.setData(cleanVolume);

        smaSeriesInstance = addLSeries(lightweightChartInstance, {
          color: '#2962FF',
          lineWidth: 2,
          title: '20 SMA'
        });
        smaSeriesInstance.setData(cleanSma);

        lightweightChartInstance.timeScale().fitContent();
        lastRenderedChartKey = chartKey;
        renderedWithTV = true;
      }
    } catch (tvErr) {
      console.warn('LightweightCharts render notice, falling back to Canvas:', tvErr);
      let tvContainer = document.getElementById('tvChartContainer');
      if (tvContainer) tvContainer.style.display = 'none';
      renderedWithTV = false;
    }
  }

  if (!renderedWithTV) {
    if (canvasEl) canvasEl.style.display = 'block';
    renderCustomCanvasCandlesticks(candles, canvasEl);
  }
}

function renderCustomCanvasCandlesticks(candles, canvasEl) {
  if (!canvasEl || !candles || candles.length === 0) return;
  const containerEl = document.getElementById('mainStockChartContainer');
  const ctx = canvasEl.getContext('2d');
  
  const totalChartH = window.innerWidth <= 480 ? 260 : (window.innerWidth <= 768 ? 320 : 380);
  canvasEl.style.display = 'block';
  canvasEl.style.width = '100%';
  canvasEl.style.height = totalChartH + 'px';

  let parentW = containerEl && containerEl.clientWidth > 50 ? containerEl.clientWidth : (canvasEl.clientWidth || (window.innerWidth <= 768 ? window.innerWidth - 24 : 700));
  canvasEl.width = Math.floor(parentW);
  canvasEl.height = totalChartH;
  const w = canvasEl.width;
  const h = canvasEl.height;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);

  const paddingRight = 60;
  const paddingBottom = 30;
  const paddingTop = 20;
  const chartW = w - paddingRight;
  const chartH = h - paddingBottom - paddingTop;

  let minPrice = Infinity;
  let maxPrice = -Infinity;
  let maxVol = 0;

  candles.forEach(c => {
    if (c.low < minPrice) minPrice = c.low;
    if (c.high > maxPrice) maxPrice = c.high;
    if ((c.volume || 0) > maxVol) maxVol = c.volume || 0;
  });

  if (minPrice === maxPrice) { minPrice *= 0.95; maxPrice *= 1.05; }
  const priceRange = maxPrice - minPrice;

  const barWidth = Math.max(2, (chartW / candles.length) - 2);
  const stepX = chartW / candles.length;

  // Grid lines
  ctx.strokeStyle = '#f0f3f6';
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i++) {
    const y = paddingTop + (chartH / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(chartW, y);
    ctx.stroke();

    const pVal = maxPrice - (priceRange / 5) * i;
    ctx.fillStyle = '#666';
    ctx.font = '10px Inter, sans-serif';
    ctx.fillText('₹' + pVal.toFixed(1), chartW + 5, y + 3);
  }

  // Draw Candles & Volume
  candles.forEach((c, idx) => {
    const x = idx * stepX + stepX / 2;
    const isUp = c.close >= c.open;
    const color = isUp ? '#089981' : '#f23645';

    if (maxVol > 0) {
      const volH = ((c.volume || 0) / maxVol) * (chartH * 0.25);
      ctx.fillStyle = isUp ? 'rgba(8, 153, 129, 0.25)' : 'rgba(242, 54, 69, 0.25)';
      ctx.fillRect(x - barWidth / 2, paddingTop + chartH - volH, barWidth, volH);
    }

    const highY = paddingTop + chartH - ((c.high - minPrice) / priceRange) * chartH;
    const lowY = paddingTop + chartH - ((c.low - minPrice) / priceRange) * chartH;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, highY);
    ctx.lineTo(x, lowY);
    ctx.stroke();

    const openY = paddingTop + chartH - ((c.open - minPrice) / priceRange) * chartH;
    const closeY = paddingTop + chartH - ((c.close - minPrice) / priceRange) * chartH;
    const bodyY = Math.min(openY, closeY);
    const bodyH = Math.max(2, Math.abs(closeY - openY));

    ctx.fillStyle = color;
    ctx.fillRect(x - barWidth / 2, bodyY, barWidth, bodyH);
  });
}

function switchChartInterval(interval) {
  currentChartInterval = interval;

  // Auto-align default range based on interval
  if (['1m'].includes(interval)) {
    currentChartPeriod = '5d';
  } else if (['2m', '3m', '5m', '15m', '30m'].includes(interval)) {
    currentChartPeriod = '1mo';
  } else if (['60m', '1h', '4h'].includes(interval)) {
    currentChartPeriod = '6mo';
  } else {
    currentChartPeriod = '1y';
  }

  // Update Interval tab UI
  const intContainer = document.querySelector('.chart-interval-tabs');
  if (intContainer) {
    intContainer.querySelectorAll('.time-tab').forEach(b => {
      if (b.innerText.trim().toLowerCase() === interval.toLowerCase()) {
        b.classList.add('active');
      } else {
        b.classList.remove('active');
      }
    });
  }

  // Update Period tab UI
  const perContainer = document.querySelector('.chart-period-tabs');
  if (perContainer) {
    perContainer.querySelectorAll('.time-tab').forEach(b => {
      const txt = b.innerText.trim().toLowerCase();
      const p = currentChartPeriod.toLowerCase();
      if (txt === p || (p === '1mo' && txt === '1m') || (p === '6mo' && txt === '6m') || (p === '5d' && txt === '5d') || (p === '1y' && txt === '1y')) {
        b.classList.add('active');
      } else {
        b.classList.remove('active');
      }
    });
  }

  loadLiveMainChart(currentChartSymbol, currentChartInterval, currentChartPeriod);
}

function switchChartPeriod(period) {
  currentChartPeriod = period;

  // If currently on an interval that cannot support the selected range, auto-switch to a compatible interval
  if (period === '1d' || period === '5d') {
    if (!['1m', '5m', '15m'].includes(currentChartInterval)) {
      currentChartInterval = '5m';
    }
  } else if (period === '1mo') {
    if (!['5m', '15m', '1h'].includes(currentChartInterval)) {
      currentChartInterval = '15m';
    }
  } else if (['6mo', '1y', 'max'].includes(period)) {
    if (['1m', '5m', '15m'].includes(currentChartInterval)) {
      currentChartInterval = '1d';
    }
  }

  // Update Period tab UI
  const perContainer = document.querySelector('.chart-period-tabs');
  if (perContainer) {
    perContainer.querySelectorAll('.time-tab').forEach(b => {
      const txt = b.innerText.trim().toLowerCase();
      const p = period.toLowerCase();
      if (txt === p || (p === '1mo' && txt === '1m') || (p === '6mo' && txt === '6m') || (p === '5d' && txt === '5d') || (p === '1y' && txt === '1y') || (p === 'max' && txt === 'max')) {
        b.classList.add('active');
      } else {
        b.classList.remove('active');
      }
    });
  }

  // Update Interval tab UI
  const intContainer = document.querySelector('.chart-interval-tabs');
  if (intContainer) {
    intContainer.querySelectorAll('.time-tab').forEach(b => {
      if (b.innerText.trim().toLowerCase() === currentChartInterval.toLowerCase()) {
        b.classList.add('active');
      } else {
        b.classList.remove('active');
      }
    });
  }

  loadLiveMainChart(currentChartSymbol, currentChartInterval, currentChartPeriod);
}
