/**
 * CTP Futures Dashboard - Charts Module
 * ECharts K-Line rendering with real-time updates via Socket.IO
 */

// Global state
let socket = null;
let chart = null;
let selectedInstrument = null;
let currentPeriod = "30min";
const instrumentsMap = {};  // instrument_id -> data
const instrumentsByExchange = {
    SHFE: [],
    DCE: [],
    CZCE: [],
    CFFEX: [],
    INE: []
};

// Exchange display names
const EXCHANGE_NAMES = {
    SHFE: "上海期货交易所",
    DCE: "大连商品交易所",
    CZCE: "郑州商品交易所",
    CFFEX: "中国金融期货交易所",
    INE: "上海国际能源交易中心"
};

// Connection state
let isConnected = false;

// DOM Elements
const loadingOverlay = document.getElementById("loading-overlay");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const searchInput = document.getElementById("search-input");

/**
 * Initialize Socket.IO connection
 */
function initSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = io(window.location.host, {
        transports: ["websocket", "polling"],
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionAttempts: 10
    });

    socket.on("connect", () => {
        console.log("Socket connected");
        setConnectionStatus(true);
        hideLoading();
    });

    socket.on("disconnect", () => {
        console.log("Socket disconnected");
        setConnectionStatus(false);
    });

    socket.on("connected", (data) => {
        console.log("Server confirmed:", data);
    });

    socket.on("tick", (data) => {
        handleTick(data);
    });

    socket.on("instruments_update", (data) => {
        handleInstrumentsUpdate(data);
    });
}

/**
 * Set connection status UI
 */
function setConnectionStatus(connected) {
    isConnected = connected;
    statusDot.className = "status-dot " + (connected ? "connected" : "disconnected");
    statusText.textContent = connected ? "Connected" : "Disconnected";
}

/**
 * Hide loading overlay
 */
function hideLoading() {
    if (loadingOverlay) {
        loadingOverlay.classList.add("loading-hidden");
    }
}

/**
 * Handle incoming tick data
 */
function handleTick(tick) {
    const { instrument_id, price, volume, bid, ask } = tick;

    if (!instrumentsMap[instrument_id]) {
        return;  // Not in our list yet
    }

    const inst = instrumentsMap[instrument_id];
    const prevPrice = inst.last_price || price;
    inst.last_price = price;
    inst.bid = bid;
    inst.ask = ask;
    inst.volume = volume;
    inst.change = price - inst.open_price;
    inst.change_pct = inst.open_price ? ((price - inst.open_price) / inst.open_price * 100) : 0;

    // Update K-line data
    updateKlineData(instrument_id, price, volume, tick.timestamp);

    // Update UI if this instrument is selected
    if (selectedInstrument === instrument_id) {
        updateContractHeader(instrument_id);
        updateChart();
    }

    // Update instrument list item
    updateInstrumentListItem(instrument_id);
}

/**
 * Handle instruments list update
 */
function handleInstrumentsUpdate(data) {
    data.forEach(inst => {
        instrumentsMap[inst.instrument_id] = inst;

        // Track by exchange
        if (inst.exchange && !instrumentsByExchange[inst.exchange]) {
            instrumentsByExchange[inst.exchange] = [];
        }
        if (inst.exchange && instrumentsByExchange[inst.exchange] && !instrumentsByExchange[inst.exchange].includes(inst.instrument_id)) {
            instrumentsByExchange[inst.exchange].push(inst.instrument_id);
        }
    });

    renderExchangeGroups();
}

/**
 * Update K-line data for an instrument
 */
function updateKlineData(instrumentId, price, volume, timestamp) {
    const periods = {
        "1min": 60,
        "5min": 300,
        "15min": 900,
        "30min": 1800,
        "1hour": 3600,
        "1day": 86400
    };

    Object.entries(periods).forEach(([periodName, periodSeconds]) => {
        const key = `${instrumentId}_${periodName}`;
        if (!window._klineCache) window._klineCache = {};

        const tsMinute = Math.floor(timestamp / 60) * 60;
        const periodTs = Math.floor(tsMinute / periodSeconds) * periodSeconds;

        if (!window._klineCache[key]) {
            window._klineCache[key] = [];
        }

        const klines = window._klineCache[key];
        if (klines.length === 0 || klines[klines.length - 1][0] < periodTs) {
            // New candle
            klines.push([periodTs, price, price, price, price, volume]);
        } else {
            // Update existing candle
            const k = klines[klines.length - 1];
            k[2] = Math.max(k[2], price);  // high
            k[3] = Math.min(k[3], price);  // low
            k[4] = price;                   // close
            k[5] += volume;                  // volume (increment)
        }
    });
}

/**
 * Get K-line data for chart
 */
function getKlineData(instrumentId, period) {
    const key = `${instrumentId}_${period}`;
    return window._klineCache?.[key] || [];
}

/**
 * Render exchange groups in left panel
 */
function renderExchangeGroups() {
    const container = document.getElementById("exchange-groups");
    if (!container) return;

    container.innerHTML = "";

    const searchTerm = searchInput?.value?.toLowerCase() || "";

    Object.entries(instrumentsByExchange).forEach(([exchange, instruments]) => {
        if (!EXCHANGE_NAMES[exchange]) return;

        const filtered = instruments.filter(iid => {
            if (!searchTerm) return true;
            return iid.toLowerCase().includes(searchTerm) ||
                   (instrumentsMap[iid]?.name || "").toLowerCase().includes(searchTerm);
        });

        if (filtered.length === 0 && searchTerm) return;

        const group = document.createElement("div");
        group.className = "exchange-group";

        const badgeClass = exchange.toLowerCase();

        group.innerHTML = `
            <div class="exchange-header" data-exchange="${exchange}">
                <div class="exchange-name">
                    <span class="exchange-badge ${badgeClass}">${exchange}</span>
                    <span>${EXCHANGE_NAMES[exchange]}</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span class="exchange-count">${filtered.length}</span>
                    <span class="exchange-toggle">▼</span>
                </div>
            </div>
            <div class="instrument-list expanded">
                ${filtered.map(iid => createInstrumentItemHTML(iid)).join("")}
            </div>
        `;

        container.appendChild(group);
    });

    // Attach event listeners
    attachGroupListeners();
    attachInstrumentListeners();
}

/**
 * Create instrument item HTML
 */
function createInstrumentItemHTML(instrumentId) {
    const inst = instrumentsMap[instrumentId] || {};
    const priceClass = inst.change >= 0 ? "up" : "down";
    const changeText = inst.change >= 0 ? "+" : "";
    const changePctText = inst.change_pct >= 0 ? "+" : "";

    return `
        <div class="instrument-item ${priceClass}" data-instrument="${instrumentId}">
            <span class="inst-symbol">${instrumentId}</span>
            <span class="inst-price ${priceClass}">${inst.last_price?.toFixed(2) || "--"}</span>
            <span class="inst-change ${priceClass}">${changePctText}${inst.change_pct?.toFixed(2) || "--"}%</span>
        </div>
    `;
}

/**
 * Update single instrument list item
 */
function updateInstrumentListItem(instrumentId) {
    const item = document.querySelector(`.instrument-item[data-instrument="${instrumentId}"]`);
    if (!item) return;

    const inst = instrumentsMap[instrumentId];
    if (!inst) return;

    const priceClass = inst.change >= 0 ? "up" : "down";
    const changePctText = inst.change_pct >= 0 ? "+" : "";

    item.className = `instrument-item ${priceClass}`;
    item.querySelector(".inst-price").className = `inst-price ${priceClass}`;
    item.querySelector(".inst-price").textContent = inst.last_price?.toFixed(2) || "--";
    item.querySelector(".inst-change").className = `inst-change ${priceClass}`;
    item.querySelector(".inst-change").textContent = `${changePctText}${inst.change_pct?.toFixed(2) || "--"}%`;
}

/**
 * Attach exchange group toggle listeners
 */
function attachGroupListeners() {
    document.querySelectorAll(".exchange-header").forEach(header => {
        header.addEventListener("click", () => {
            const list = header.nextElementSibling;
            const toggle = header.querySelector(".exchange-toggle");
            list.classList.toggle("expanded");
            toggle.classList.toggle("collapsed");
        });
    });
}

/**
 * Attach instrument item click listeners
 */
function attachInstrumentListeners() {
    document.querySelectorAll(".instrument-item").forEach(item => {
        item.addEventListener("click", () => {
            const instrumentId = item.dataset.instrument;
            selectInstrument(instrumentId);

            // Update selected state
            document.querySelectorAll(".instrument-item").forEach(i => i.classList.remove("selected"));
            item.classList.add("selected");
        });
    });
}

/**
 * Select an instrument and load its chart
 */
function selectInstrument(instrumentId) {
    selectedInstrument = instrumentId;
    const inst = instrumentsMap[instrumentId];

    if (!inst) return;

    // Update header
    document.getElementById("contract-symbol").textContent = instrumentId;
    document.getElementById("contract-name").textContent = inst.name || instrumentId;
    document.getElementById("price-display").style.display = "flex";
    document.getElementById("contract-stats").style.display = "flex";

    updateContractHeader(instrumentId);

    // Load chart data
    loadChartData(instrumentId, currentPeriod);
}

/**
 * Update contract header with current data
 */
function updateContractHeader(instrumentId) {
    const inst = instrumentsMap[instrumentId];
    if (!inst) return;

    const priceMain = document.getElementById("price-main");
    const priceChange = document.getElementById("price-change");
    const statVolume = document.getElementById("stat-volume");
    const statOi = document.getElementById("stat-oi");
    const statBid = document.getElementById("stat-bid");
    const statAsk = document.getElementById("stat-ask");

    priceMain.textContent = inst.last_price?.toFixed(2) || "--";
    priceMain.className = `price-main ${inst.change >= 0 ? "up" : "down"}`;

    const changeText = (inst.change >= 0 ? "+" : "") + (inst.change?.toFixed(2) || "--");
    const pctText = (inst.change_pct >= 0 ? "+" : "") + (inst.change_pct?.toFixed(2) || "--") + "%";
    priceChange.textContent = `${changeText} (${pctText})`;
    priceChange.className = `price-change ${inst.change >= 0 ? "up" : "down"}`;

    statVolume.textContent = formatNumber(inst.volume);
    statOi.textContent = formatNumber(inst.open_interest);
    statBid.textContent = inst.bid?.toFixed(2) || "--";
    statAsk.textContent = inst.ask?.toFixed(2) || "--";
}

/**
 * Format large numbers with K/M suffix
 */
function formatNumber(num) {
    if (num == null || num === 0) return "--";
    if (num >= 1000000) return (num / 1000000).toFixed(2) + "M";
    if (num >= 1000) return (num / 1000).toFixed(2) + "K";
    return num.toString();
}

/**
 * Load chart data from server
 */
async function loadChartData(instrumentId, period) {
    try {
        const resp = await fetch(`/api/kline/${instrumentId}/${period}`);
        const data = await resp.json();

        // Merge with local cache
        window._klineCache = window._klineCache || {};
        const key = `${instrumentId}_${period}`;
        window._klineCache[key] = data;

        updateChart();
    } catch (e) {
        console.error("Failed to load chart data:", e);
    }
}

/**
 * Initialize ECharts instance
 */
function initChart() {
    const container = document.getElementById("kline-chart");
    if (!container) return;

    chart = echarts.init(container, "dark");

    const option = {
        backgroundColor: "transparent",
        animation: false,
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "cross" },
            backgroundColor: "rgba(13, 17, 23, 0.95)",
            borderColor: "#1e2a3a",
            textStyle: { color: "#e6edf3", fontFamily: "JetBrains Mono" },
            formatter: (params) => {
                if (!params || !params[0]) return "";
                const d = params[0];
                const ts = new Date(d.value[0]);
                return `
                    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;">
                        <div style="color:#8b949e;margin-bottom:4px;">${ts.toLocaleString()}</div>
                        <div>O: <span style="color:#e6edf3">${d.value[1]?.toFixed(2)}</span></div>
                        <div>H: <span style="color:#00ff88">${d.value[2]?.toFixed(2)}</span></div>
                        <div>L: <span style="color:#ff3366">${d.value[3]?.toFixed(2)}</span></div>
                        <div>C: <span style="color:#e6edf3">${d.value[4]?.toFixed(2)}</span></div>
                        <div>Vol: <span style="color:#58a6ff">${formatNumber(d.value[5])}</span></div>
                    </div>
                `;
            }
        },
        grid: { left: 60, right: 20, top: 20, bottom: 60 },
        xAxis: {
            type: "time",
            axisLine: { lineStyle: { color: "#1e2a3a" } },
            axisLabel: { color: "#484f58", fontFamily: "JetBrains Mono", fontSize: 10 },
            splitLine: { show: false }
        },
        yAxis: {
            scale: true,
            position: "right",
            axisLine: { lineStyle: { color: "#1e2a3a" } },
            axisLabel: { color: "#484f58", fontFamily: "JetBrains Mono", fontSize: 10 },
            splitLine: { lineStyle: { color: "#1e2a3a", type: "dashed" } }
        },
        dataZoom: [
            { type: "inside", xAxisIndex: 0, start: 70, end: 100 },
            { type: "slider", xAxisIndex: 0, start: 70, end: 100, height: 20, bottom: 10,
              borderColor: "#1e2a3a", backgroundColor: "#0d1117",
              fillerColor: "rgba(88, 166, 255, 0.2)", handleStyle: { color: "#58a6ff" },
              textStyle: { color: "#484f58" } }
        ],
        series: [{
            type: "candlestick",
            name: "KLine",
            data: [],
            itemStyle: {
                color: "#00ff88",       // up body
                color0: "#ff3366",      // down body
                borderColor: "#00ff88",
                borderColor0: "#ff3366"
            }
        }, {
            type: "line",
            name: "MA5",
            data: [],
            smooth: true,
            symbol: "none",
            lineStyle: { color: "#f0c040", width: 1, opacity: 0.7 }
        }, {
            type: "line",
            name: "MA10",
            data: [],
            smooth: true,
            symbol: "none",
            lineStyle: { color: "#58a6ff", width: 1, opacity: 0.7 }
        }]
    };

    chart.setOption(option);

    // Resize handler
    window.addEventListener("resize", () => {
        chart?.resize();
    });
}

/**
 * Update chart with current data
 */
function updateChart() {
    if (!chart || !selectedInstrument) return;

    const klines = getKlineData(selectedInstrument, currentPeriod);
    const candles = klines.map(k => [k[0], k[1], k[2], k[3], k[4]]);

    // Calculate MA
    const closes = klines.map(k => k[4]);
    const ma5 = calculateMA(closes, 5);
    const ma10 = calculateMA(closes, 10);

    const ma5Data = ma5.map((v, i) => [klines[i][0], v]);
    const ma10Data = ma10.map((v, i) => [klines[i][0], v]);

    chart.setOption({
        series: [{
            data: candles
        }, {
            data: ma5Data
        }, {
            data: ma10Data
        }]
    });

    // Update info
    document.getElementById("chart-candles").textContent = `${candles.length} candles`;

    if (klines.length > 0) {
        const first = new Date(klines[0][0]);
        const last = new Date(klines[klines.length - 1][0]);
        document.getElementById("chart-range").textContent =
            `${first.toLocaleDateString()} - ${last.toLocaleDateString()}`;
    }
}

/**
 * Calculate Moving Average
 */
function calculateMA(closes, period) {
    const result = [];
    for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) {
            result.push(null);
        } else {
            const sum = closes.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
            result.push(sum / period);
        }
    }
    return result;
}

/**
 * Period button click handler
 */
function setupPeriodButtons() {
    document.querySelectorAll(".period-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".period-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentPeriod = btn.dataset.period;

            if (selectedInstrument) {
                loadChartData(selectedInstrument, currentPeriod);
            }
        });
    });
}

/**
 * Search input handler
 */
function setupSearch() {
    if (searchInput) {
        searchInput.addEventListener("input", () => {
            renderExchangeGroups();
        });
    }
}

/**
 * Fetch initial instruments list
 */
async function fetchInstruments() {
    try {
        const resp = await fetch("/api/instruments");
        const data = await resp.json();
        handleInstrumentsUpdate(data);

        // Auto-select first instrument immediately after data loads
        if (Object.keys(instrumentsMap).length > 0 && !selectedInstrument) {
            const firstId = Object.keys(instrumentsMap)[0];
            selectInstrument(firstId);
        }
    } catch (e) {
        console.error("Failed to fetch instruments:", e);
    }
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
    initChart();
    initSocket();
    setupPeriodButtons();
    setupSearch();

    // Initial fetch - chart renders immediately when data arrives
    fetchInstruments();
});
