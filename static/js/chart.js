//Chartink's ----------- @kodebuds Reserch and Development ------------------------

//Import necessary modules and libraries

import { createChart } from './lightweight.js';
import { createNavbar, injectStyles } from './top_navbar.js';
import { enhanceNavbar } from './search.js';
import { initializeSettings, getCurrentTimezone, getTimeFormat } from './settings.js';
import { tickMarkFormatter, addCustomCrosshairLabel } from './timezone.js';
import { FootprintSeries } from './plugins/footprint.js';
import { RoundedCandlestickSeries } from './plugins/rounded-candles.js';
import { RectangleDrawingTool } from './drawing-tool.js';

// Initialize Socket.IO connection
let socket = null;
const initializeSocket = () => {
    if (!socket) {
        socket = io();

        socket.on('connect', () => {
            console.log('Connected to server');
        });

        socket.on('disconnect', () => {
            console.log('Disconnected from server');
        });

        socket.on('live_data_update', (data) => {
            handleLiveDataUpdate(data);
        });

        socket.on('subscription_success', (data) => {
            console.log(`Successfully subscribed to ${data.symbol} for ${data.chart_id}`, data);
        });

        socket.on('unsubscription_success', (data) => {
            console.log(`Successfully unsubscribed from ${data.symbol} for ${data.chart_id}`, data);
        });

        socket.on('error', (data) => {
            console.error('Socket error:', data.message);
        });

        socket.on('live_feed_error', (data) => {
            console.error(`Live feed error for ${data.symbol}:`, data.error);
        });

        socket.on('live_feed_closed', (data) => {
            console.log(`Live feed closed for ${data.symbol}:`, data.message);
        });
    }
    return socket;
};

// LAYOUTS maps to simple grid-template strings for default layouts (index = numCharts-1)
const LAYOUTS = [
    '1fr / 1fr',               // 1 chart
    '1fr / 1fr 1fr',           // 2 charts (1 row, 2 cols)
    '1fr / 1fr 1fr 1fr',       // 3 charts (1 row, 3 cols) - legacy
    '1fr 1fr / 1fr 1fr',       // 4 charts (2 rows, 2 cols)    
];
const CHART_DEFAULTS = {
    symbol: 'NSE:NIFTY26JANFUT',
    timeframe: '5m',
    layout: { attributionLogo: false, textColor: '#B2B5BE', background: { type: 'solid', color: '#181A20' } },
    grid: { vertLines: { color: '#22242B' }, horzLines: { color: '#22242B' } },
    timeScale: {
        borderColor: '#363C4E',
        rightOffset: 6,        
        fixLeftEdge: true,
        timeVisible: true,
    },
    rightPriceScale: { borderColor: '#363C4E', setAutoScale: true },
    crosshair: { mode: 0, vertLine: { labelVisible: false } }
};

// Global state
const state = {
    chartRegistry: [],
    selectedChartIndex: 0,
    currentSymbol: CHART_DEFAULTS.symbol,
    currentTimeframe: CHART_DEFAULTS.timeframe,
    isMaximized: false,
    prevLayout: null,
    timezone: getCurrentTimezone(),
    use12Hour: getTimeFormat() === '12h'
};

// Expose necessary state to window for cross-module interaction
window.selectedChartIndex = 0; // Will be updated when chart is selected
window.chartRegistry = state.chartRegistry;

// ================================
// LIVE DATA MANAGEMENT
// ================================
const LiveDataManager = {
    activeSubscriptions: new Map(), // chartId -> subscription details
    
    subscribeToSymbol(chartId, symbol, timeframe, bucket_size = 0.05, multiplier = 100, histSeed = null) {
        // Unsubscribe from previous symbol if exists
        this.unsubscribeFromSymbol(chartId);
        
        const socket = initializeSocket();
        if (socket) {
            const subscriptionData = {
                symbol,
                timeframe,
                bucket_size,
                multiplier,
                chart_id: chartId,
                hist_seed: histSeed // Include historical seeding data
            };
            
            //console.log(`Subscribing ${chartId} to ${symbol}-${timeframe} with bucket_size=${bucket_size}, multiplier=${multiplier}`);
            socket.emit('subscribe_symbol', subscriptionData);
            this.activeSubscriptions.set(chartId, subscriptionData);
            
            console.log(`Subscribed to live updates for ${symbol} on ${chartId}`);
        }
    },
    
    unsubscribeFromSymbol(chartId) {
        const subscription = this.activeSubscriptions.get(chartId);
        if (subscription) {
            const socket = initializeSocket();
            if (socket) {
                socket.emit('unsubscribe_symbol', {
                    symbol: subscription.symbol,
                    chart_id: chartId
                });
            }
            this.activeSubscriptions.delete(chartId);
            console.log(`Unsubscribed from ${subscription.symbol} on ${chartId}`);
        }
    },
    
    unsubscribeAll() {
        this.activeSubscriptions.forEach((subscription, chartId) => {
            this.unsubscribeFromSymbol(chartId);
        });
    }
};

// Handle live data updates from WebSocket
function handleLiveDataUpdate(data) {
    const { symbol, chart_id, data: candleData, timeframe, timestamp } = data;
    
    // Add debugging information
    // console.log(`Received live data update: symbol=${symbol}, chart_id=${chart_id}, timeframe=${timeframe}`);
    
    // Find the corresponding chart
    let chartObj = null;

    // Prefer matching by chart_id (normalize to string) since server may send chart ids
    if (chart_id) {
        const idStr = String(chart_id);
        chartObj = state.chartRegistry.find(obj => obj.container && String(obj.container.id) === idStr);
        if (!chartObj) {
            // Also try matching partial ids (some code may use 'chart-0' vs '0')
            chartObj = state.chartRegistry.find(obj => obj.container && String(obj.container.id).endsWith(String(idStr)));
        }
        if (chartObj) {
            // quick sanity check: log when chart found by id
            // console.debug(`Matched live update to chart by id: ${idStr}`);
        }
    }

    // Fallback: match by symbol + timeframe (helps when chart ids differ between client/server)
    if (!chartObj && symbol) {
        chartObj = state.chartRegistry.find(obj => obj.symbol === symbol && obj.timeframe === timeframe);
        if (chartObj) {
            console.debug(`Live update matched by symbol+timeframe fallback: ${symbol}-${timeframe} (chart ${chartObj.container?.id})`);
        }
    }

    if (!chartObj) {
        console.warn(`Chart not found for live data update: chart_id=${chart_id}, symbol=${symbol}, timeframe=${timeframe}`);
        console.log('Available charts:', state.chartRegistry.map(obj => ({ 
            id: obj.container?.id, 
            symbol: obj.symbol, 
            timeframe: obj.timeframe 
        })));
        return;
    }
    //console.log(`Found chart ${chartIndex} for update: ${symbol}-${chartObj.timeframe}`);
    
    try {
        // Update the live candle data
        updateChartWithLiveData(chartObj, candleData, timestamp);
    } catch (error) {
        console.error('Error updating chart with live data:', error);
    }
}

// Update chart with live candlestick data
function updateChartWithLiveData(chartObj, candleData, timestamp) {
    if (!chartObj.candlestickSeries || !candleData) {
        return;
    }
    
    // Convert the live data to required format
    const tvCandle = {
        time: candleData.time || Math.floor(timestamp / 1000),
        open: candleData.open,
        high: candleData.high,
        low: candleData.low,
        close: candleData.close,
        volume: candleData.volume || 0
    };
    // Attach delta fields (ensure numeric 0 is preserved) and persist on chartObj
    tvCandle.delta = (typeof candleData.delta === 'number') ? candleData.delta : (candleData.delta || 0);
    tvCandle.cum_delta = (typeof candleData.cum_delta === 'number') ? candleData.cum_delta : (candleData.cum_delta || 0);
    try { chartObj.latestCandle = tvCandle; } catch (e) { /* ignore */ }

    // Update candlestick series
    chartObj.candlestickSeries.update(tvCandle);
    
    // Update footprint series if available and data has footprint
    if (chartObj.footprintSeries && candleData.footprint) {
        const footprintData = {
            ...tvCandle,
            delta: candleData.delta || 0,
            cum_delta: candleData.cum_delta || 0,
            // 'poc' removed from payload; renderer should derive from close if needed
            footprint: candleData.footprint
        };
        
        chartObj.footprintSeries.update(footprintData);
    }
    
    
    // Update legend for this chart so even non-selected charts show latest candle values
    if (chartObj.updateLegend && !chartObj._isCursorLegend) {
        // Throttle legend updates for better performance
        if (!chartObj._legendThrottled) {
            chartObj._legendThrottled = true;
            requestAnimationFrame(() => {
                try {
                    chartObj.updateLegend({
                        time: tvCandle.time,
                        latestCandle: tvCandle,
                        seriesData: new Map([
                            [chartObj.candlestickSeries, {
                                open: tvCandle.open,
                                high: tvCandle.high,
                                low: tvCandle.low,
                                close: tvCandle.close,
                                volume: tvCandle.volume,
                                delta: tvCandle.delta,
                                cum_delta: tvCandle.cum_delta
                            }]
                        ])
                    });
                } catch (e) {
                    console.error('Error calling updateLegend after live update', e);
                }
                chartObj._legendThrottled = false;
            });
        }
    }
}

// ================================
// LOCAL STORAGE MANAGEMENT
// ================================
const LocalStorage = {
    // Layout persistence
    saveLayout() {
        try {
            const layoutData = {
                numCharts: state.chartRegistry.length,
                selectedChartIndex: state.selectedChartIndex,
                charts: state.chartRegistry.map((obj, index) => ({
                    symbol: obj.symbol,
                    timeframe: obj.timeframe,
                    chartType: obj.chartType,
                    bucket_size: obj.bucket_size || 0.05,
                    multiplier: obj.multiplier || 100
                })),
                isMaximized: state.isMaximized,
                prevLayout: state.prevLayout,
                layoutVariant: state.layoutVariant || null,
                timestamp: Date.now()
            };
            localStorage.setItem('chartLayout', JSON.stringify(layoutData));
            // console.log('Layout saved to localStorage:', layoutData);
        } catch (error) {
            console.error('Failed to save layout to localStorage:', error);
        }
    },

    loadLayout() {
        try {
            const saved = localStorage.getItem('chartLayout');
            if (!saved) return null;
            
            const layoutData = JSON.parse(saved);
            
            // Validate the layout data
            if (!layoutData.numCharts || !Array.isArray(layoutData.charts) || 
                layoutData.numCharts !== layoutData.charts.length) {
                console.warn('Invalid layout data found, ignoring');
                return null;
            }

            // console.log('Loaded layout from localStorage:', layoutData);
            return layoutData;
        } catch (error) {
            console.error('Failed to load layout from localStorage:', error);
            return null;
        }
    },

    applyLayout(layoutData) {
        if (!layoutData) return false;
        
        try {
            // Create the grid layout first
            const grid = createGridContainer();
            state.chartRegistry.forEach(cleanupChart);
            state.chartRegistry.length = 0;
            grid.innerHTML = '';
            
            const numCharts = layoutData.numCharts;
            // honor variant if present (eg. split-right)
            if (layoutData.layoutVariant === 'split-right') {
                grid.style.gridTemplate = '1fr 1fr / 1fr 1fr';
            } else {
                grid.style.gridTemplate = LAYOUTS[Math.max(0, Math.min(numCharts - 1, LAYOUTS.length - 1))];
            }
            
            // Create containers and chart instances
            for (let i = 0; i < numCharts; i++) {
                const container = createChartContainer(i);
                container.addEventListener('click', (e) => {
                    if (e.altKey) { 
                        e.preventDefault(); 
                        maximizeOrRestoreChart(i); 
                    } else {
                        setSelectedChart(i);
                    }
                });
                grid.appendChild(container);
                
                const chartConfig = layoutData.charts[i];
                createChartInstance(container, chartConfig.symbol, chartConfig.timeframe);
                
                // Apply the saved chart configuration
                const chartObj = state.chartRegistry[i];
                if (chartObj) {
                    chartObj.bucket_size = chartConfig.bucket_size || 0.05;
                    chartObj.multiplier = chartConfig.multiplier || 100;
                    chartObj.chartType = chartConfig.chartType || 'candlestick';

                    // Set initial effective bucket size based on this chart's configuration
                    chartObj.effectiveBucketSize = chartObj.bucket_size * chartObj.multiplier;

                    // Apply footprint settings for this chart
                    if (chartObj.footprintSeries && typeof chartObj.footprintSeries.applyOptions === 'function') {
                        try {
                            chartObj.footprintSeries.applyOptions({
                                tickSize: chartObj.effectiveBucketSize
                            });
                        } catch (e) {}
                    }
                }
            }
            // If saved variant requires special placement, apply it
            if (layoutData.layoutVariant === 'split-right') {
                const c0 = document.getElementById('chart-0');
                const c1 = document.getElementById('chart-1');
                const c2 = document.getElementById('chart-2');
                if (c0) {
                    c0.style.gridRow = '1 / span 2';
                    c0.style.gridColumn = '1 / span 1';
                }
                if (c1) {
                    c1.style.gridRow = '1 / span 1';
                    c1.style.gridColumn = '2 / span 1';
                }
                if (c2) {
                    c2.style.gridRow = '2 / span 1';
                    c2.style.gridColumn = '2 / span 1';
                }
            }
            
            // Restore state
            state.selectedChartIndex = Math.max(0, Math.min(layoutData.selectedChartIndex || 0, numCharts - 1));
            state.isMaximized = layoutData.isMaximized || false;
            state.prevLayout = layoutData.prevLayout;
            // Restore variant so maximize/restore logic can use it
            state.layoutVariant = layoutData.layoutVariant || null;
            
            // Update layout button highlight (handle variant -> button mapping)
            const activeButtonNum = (layoutData.layoutVariant === 'split-right' && numCharts === 3) ? 5 : numCharts;
            updateLayoutButtonHighlight(activeButtonNum);
            
            // Set selected chart and load data
            setSelectedChart(state.selectedChartIndex);
            this.loadAllChartsDataFromLayout(layoutData);
            // Clear any temporary saved grid positions from previous sessions
            if (state._savedGridPositions) delete state._savedGridPositions;
            return true;
        } catch (error) {
            console.error('Failed to apply layout from storage:', error);
            return false;
        }
    },

    loadAllChartsDataFromLayout(layoutData) {
        layoutData.charts.forEach((chartConfig, idx) => {
            const chartObj = state.chartRegistry[idx];
            if (chartObj) {
                loadHistoricalData(idx, chartConfig.symbol, chartConfig.timeframe, 
                                  chartConfig.bucket_size, chartConfig.multiplier);
                
                // Apply chart type after data is loaded
                setTimeout(() => {
                    switchChartType(chartObj, chartConfig.chartType || 'candlestick');
                    setSelectedChart(state.selectedChartIndex);
                }, 100);
            }
        });
    },

    clearLayout() {
        try {
            localStorage.removeItem('chartLayout');
            console.log('Chart layout cleared from localStorage');
        } catch (error) {
            console.error('Failed to clear layout from localStorage:', error);
        }
    },

    // Chart settings persistence (per chart)
    saveChartSettings(chartId, bucket_size, multiplier) {
        try {
            const payload = { bucket_size, multiplier };
            localStorage.setItem(`chartSettings_${chartId}`, JSON.stringify(payload));
        } catch (error) {
            console.error('Failed to save chart settings:', error);
        }
    },

    loadChartSettings(chartId) {
        try {
            const saved = localStorage.getItem(`chartSettings_${chartId}`);
            if (saved) {
                const obj = JSON.parse(saved);
                return {
                    bucket_size: typeof obj.bucket_size === 'number' ? obj.bucket_size : 0.05,
                    multiplier: typeof obj.multiplier === 'number' ? obj.multiplier : 100
                };
            }
        } catch (error) {
            console.error('Failed to load chart settings:', error);
        }
        return { bucket_size: 0.05, multiplier: 100 };
    },

    // Time settings persistence
    saveTimeSettings(timezone, use12Hour) {
        try {
            // Read existing settings to preserve other values
            const existing = JSON.parse(localStorage.getItem('chartSettings') || '{}');
            const updated = {
                ...existing,
                timezone: timezone,
                timeFormat: use12Hour ? '12h' : '24h'
            };
            localStorage.setItem('chartSettings', JSON.stringify(updated));
        } catch (error) {
            console.error('Failed to save time settings:', error);
        }
    },

    loadTimeSettings() {
        try {
            // Use the same key as settings.js
            const saved = localStorage.getItem('chartSettings');
            if (saved) {
                const obj = JSON.parse(saved);
                return {
                    timezone: obj.timezone || getCurrentTimezone(),
                    use12Hour: obj.timeFormat === '12h'
                };
            }
        } catch (error) {
            console.error('Failed to load time settings:', error);
        }
        return { timezone: getCurrentTimezone(), use12Hour: getTimeFormat() === '12h' };
    }
};

// Expose debug function globally
window.clearChartLayout = () => LocalStorage.clearLayout();

// Initialize app
injectStyles();
createNavbar();
initializeSettings();

// Utility functions
const getTickFormatter = () => (time, tickType, locale) =>
    tickMarkFormatter(time, tickType, state.timezone, state.use12Hour, locale);

// Centralized right offset management
const updateChartRightOffset = (chart, chartType) => {
    const rightOffset = chartType === 'footprint' ? 3 : 10;
    chart.applyOptions({ timeScale: { rightOffset } });
};

// Button hover effect utility
const addButtonHoverEffect = (button, normalBg = '#363C4E', hoverBg = '#4A4F63') => {
    button.addEventListener('mouseenter', () => {
        button.style.backgroundColor = hoverBg;
        button.style.opacity = '1';
    });
    button.addEventListener('mouseleave', () => {
        button.style.backgroundColor = normalBg;
        button.style.opacity = '0.9';
    });
};

// Centralized chart type switching logic
const switchChartType = (chartObj, newType) => {
    if (!chartObj || chartObj.chartType === newType) return;
    
    chartObj.chartType = newType;
    const isFootprint = newType === 'footprint';
    
    chartObj.candlestickSeries?.applyOptions({ visible: !isFootprint });
    chartObj.footprintSeries?.applyOptions({ visible: isFootprint });
    updateChartRightOffset(chartObj.chart, newType);
};

const createGridContainer = () => {
    let grid = document.querySelector('.charts-grid');
    if (!grid) {
        grid = document.createElement('div');
        grid.className = 'charts-grid';
        Object.assign(grid.style, {
            display: 'grid', position: 'fixed', left: '0', right: '0', top: '40px', 
            height: 'calc(100vh - 40px)', gap: '1px', padding: '1px', 
            backgroundColor: '#23262F', zIndex: '1', width: '100vw', bottom: '0', 
            boxSizing: 'border-box'
        });
        document.body.appendChild(grid);
        new ResizeObserver(resizeAllCharts).observe(grid);
    }
    return grid;
};

const cleanupChart = (obj) => {
    if (obj.cleanup) obj.cleanup();
    if (obj.resizeObserver) obj.resizeObserver.disconnect();
    // Properly destroy both series instances to prevent memory leaks and conflicts
    if (obj.candlestickSeries?.destroy) obj.candlestickSeries.destroy();
    if (obj.footprintSeries?.destroy) obj.footprintSeries.destroy();
    if (obj.chart) obj.chart.remove();
};

const createChartContainer = (index) => {
    const container = document.createElement('div');
    container.id = `chart-${index}`;
    Object.assign(container.style, {
        position: 'relative', border: '1px solid transparent', borderRadius: '3px',
        transition: 'all 0.2s ease', boxSizing: 'border-box', margin: '0px',
        width: '100%', height: '100%', minHeight: 0, minWidth: 0,
        overflow: 'hidden', display: 'flex', flexDirection: 'column'
    });
    // Click handler is added by callers so they can handle modifier keys (Alt/Shift)
    return container;
};

// Enhanced layout management with multi-timeframe support
const setLayout = (numCharts, variant = null) => {
    const grid = createGridContainer();
    // Cleanup existing charts
    state.chartRegistry.forEach(cleanupChart);
    state.chartRegistry.length = 0;
    grid.innerHTML = '';
    // store active layout variant so it can be saved/restored
    state.layoutVariant = variant || null;

    // Choose grid template. If a variant is requested, use a template adequate for it.
    if (variant === 'split-right') {
        // 2 rows x 2 cols grid: left column will be spanned by chart 0, right column split into two charts
        grid.style.gridTemplate = '1fr 1fr / 1fr 1fr';
    } else {
        grid.style.gridTemplate = LAYOUTS[Math.max(0, Math.min(numCharts - 1, LAYOUTS.length - 1))];
    }
    
    // Default timeframes for multi-chart layouts (different timeframes for same symbol analysis)
    // Force all charts to use 5m timeframe in multi-chart layout
    const defaultTimeframes = ['5m', '5m', '5m', '5m'];
    
    for (let i = 0; i < numCharts; i++) {
        const container = createChartContainer(i);
        container.addEventListener('click', (e) => {
            if (e.altKey) { 
                e.preventDefault(); 
                maximizeOrRestoreChart(i); 
            } else {
                setSelectedChart(i);
            }
        });
        grid.appendChild(container);
        
    // Always use 5m timeframe for all charts
    const timeframe = '5m';
    createChartInstance(container, state.currentSymbol, timeframe);
    }
    // Special placement for split-right variant when requested via button
    if (variant === 'split-right') {
        // We expect exactly 3 charts to be created for this variant
        // place chart-0 to span both rows in the left column
        const c0 = document.getElementById('chart-0');
        const c1 = document.getElementById('chart-1');
        const c2 = document.getElementById('chart-2');
        if (c0) {
            c0.style.gridRow = '1 / span 2';
            c0.style.gridColumn = '1 / span 1';
        }
        if (c1) {
            c1.style.gridRow = '1 / span 1';
            c1.style.gridColumn = '2 / span 1';
        }
        if (c2) {
            c2.style.gridRow = '2 / span 1';
            c2.style.gridColumn = '2 / span 1';
        }
    }
    setSelectedChart(0);
    // Load all charts data after layout is set
    loadAllChartsDataWithDifferentTimeframes(numCharts);
    // Save layout to storage after creating charts
    setTimeout(() => LocalStorage.saveLayout(), 100);
};

// Enhanced data loading for different timeframes
function loadAllChartsDataWithDifferentTimeframes(numCharts) {
    // Always use 5m for all charts
    const chartConfigs = state.chartRegistry.map((obj, idx) => ({
        chartIdx: idx,
        symbol: obj.symbol,
        timeframe: '5m',
        bucket_size: obj.bucket_size || 0.05,
        multiplier: obj.multiplier || 100
    }));
    console.log('Loading charts with configurations:', chartConfigs);
    chartConfigs.forEach(async (cfg) => {
        try {
            // Update chart object with the timeframe
            const chartObj = state.chartRegistry[cfg.chartIdx];
            if (chartObj) {
                chartObj.timeframe = cfg.timeframe;
            }
            await updateChartData(cfg.chartIdx, cfg.symbol, cfg.timeframe, cfg.bucket_size, cfg.multiplier);
        } catch (error) {
            console.error(`Error loading data for chart ${cfg.chartIdx}:`, error);
        }
    });
}

// Maximize or restore a chart in the grid
function maximizeOrRestoreChart(idx) {
    const grid = document.querySelector('.charts-grid');
    if (!grid) return;
    if (!state.isMaximized) {
        // Save previous layout template and variant so we can restore exactly
        state.prevLayout = grid.style.gridTemplate;
        state.prevLayoutVariant = state.layoutVariant || null;
        // Save any inline grid position overrides so we can restore them later
        state._savedGridPositions = state.chartRegistry.map(obj => ({
            id: obj.container.id,
            gridRow: obj.container.style.gridRow || null,
            gridColumn: obj.container.style.gridColumn || null,
            display: obj.container.style.display || null
        }));

        // Hide other charts and show only the selected one
        state.chartRegistry.forEach((obj, i) => {
            if (i === idx) {
                obj.container.style.display = 'flex';
                // clear any positioning so it can fill the single-chart grid
                obj.container.style.gridRow = '';
                obj.container.style.gridColumn = '';
            } else {
                obj.container.style.display = 'none';
            }
        });

        // Set grid to single cell
        grid.style.gridTemplate = '1fr / 1fr';
        // mark maximized state
        state.isMaximized = true;
        // keep layoutVariant available in prevLayoutVariant; clear active variant while maximized
        state.layoutVariant = null;
        setSelectedChart(idx);
    } else {
        // Restore display for all charts
        state.chartRegistry.forEach(obj => { obj.container.style.display = 'flex'; });

        // Restore grid template from saved prevLayout
        if (state.prevLayout) grid.style.gridTemplate = state.prevLayout;

        // Restore saved inline positions if present
        if (Array.isArray(state._savedGridPositions)) {
            state._savedGridPositions.forEach(pos => {
                const el = document.getElementById(pos.id);
                if (!el) return;
                if (pos.gridRow) el.style.gridRow = pos.gridRow; else el.style.gridRow = '';
                if (pos.gridColumn) el.style.gridColumn = pos.gridColumn; else el.style.gridColumn = '';
                if (pos.display) el.style.display = pos.display; else el.style.display = 'flex';
            });
        }

        // If the previous layout variant was split-right, reapply its placement
        if (state.prevLayoutVariant === 'split-right') {
            const c0 = document.getElementById('chart-0');
            const c1 = document.getElementById('chart-1');
            const c2 = document.getElementById('chart-2');
            if (c0) {
                c0.style.gridRow = '1 / span 2';
                c0.style.gridColumn = '1 / span 1';
            }
            if (c1) {
                c1.style.gridRow = '1 / span 1';
                c1.style.gridColumn = '2 / span 1';
            }
            if (c2) {
                c2.style.gridRow = '2 / span 1';
                c2.style.gridColumn = '2 / span 1';
            }
            // restore active variant
            state.layoutVariant = 'split-right';
        } else {
            // restore previously active variant (may be null)
            state.layoutVariant = state.prevLayoutVariant || null;
        }

        state.isMaximized = false;
        // Force reapply styles/highlight even if the selected index is unchanged
        setSelectedChart(state.selectedChartIndex, true);
    }
    resizeAllCharts();
    // Save layout when maximize state changes
    LocalStorage.saveLayout();
}

// Update the navbar to reflect the selected chart's symbol and timeframe
function updateNavbarSymbolAndTimeframe() {
    const obj = state.chartRegistry[state.selectedChartIndex];
    if (!obj) return;
    const symbolEl = document.getElementById('current-symbol');
    if (symbolEl) symbolEl.textContent = obj.symbol;
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.classList.toggle('active', btn.textContent.trim() === obj.timeframe);
    });
}

// Set the selected chart and update UI highlights
function setSelectedChart(index, force = false) {
    if (state.selectedChartIndex === index && !force) return;
    state.selectedChartIndex = index;
    
    // Update the global selectedChartIndex for cross-module access
    window.selectedChartIndex = index;
    
    state.chartRegistry.forEach((obj, i) => {
        const isActive = i === index;
        let background = 'transparent';
        if (isActive) {
            if (obj.chartType === 'footprint') {
                background = '#363C4E'; // hover background for footprint chart
            } else {
                background = 'rgba(102, 107, 120, 0.03)';
            }
        }
        Object.assign(obj.container.style, {
            border: isActive ? '1.5px solid #666B78' : '1px solid transparent',
            boxShadow: isActive ? '0 0 0 0.5px rgba(102, 107, 120, 0.4)' : 'none',
            background
        });
    });
    updateNavbarSymbolAndTimeframe();
    // Save layout when selected chart changes
    if (state.chartRegistry.length > 0) {
        LocalStorage.saveLayout();
    }
    
    // Dispatch chart selected event for other components to listen to
    document.dispatchEvent(new CustomEvent('chartSelected', {
        detail: { 
            index,
            chartId: `chart-${index}`,
            chartObj: state.chartRegistry[index]
        }
    }));
}

// Chart creation with optimized legend and event handling
function createChartInstance(container, symbol, timeframe) {
    const chartConfig = {
        ...CHART_DEFAULTS,
        timeScale: {
            ...CHART_DEFAULTS.timeScale,
            tickMarkFormatter: getTickFormatter(),
            // allow longer labels like "09Aug 13:05"
            tickMarkMaxCharacterLength: 12
        },
        width: container.clientWidth,
        height: container.clientHeight
    };
    const chart = createChart(container, chartConfig);
    
    // Create legend element
    const legend = document.createElement('div');
    Object.assign(legend.style, {
        position: 'absolute', left: '12px', top: '12px', zIndex: '2',
        fontSize: '11px', fontFamily: 'sans-serif', lineHeight: '18px',
        fontWeight: '300', pointerEvents: 'none', color: '#B2B5BE'
    });
    container.appendChild(legend);

    // Button visibility controller - streamlined logic
    const updateScrollButtonVisibility = () => {
        try {
            const visibleRange = chart.timeScale().getVisibleRange();
            if (!visibleRange) {
                scrollToRealtimeBtn.style.display = 'none';
                return;
            }
            
            const seriesData = candlestickSeries?.data?.();
            if (!seriesData || !seriesData.length) {
                scrollToRealtimeBtn.style.display = 'none';
                return;
            }
            
            // Get latest data point timestamp
            const latestDataTime = seriesData[seriesData.length - 1].time;
            
            // Show button if not at latest data (with small buffer for minor variations)
            const isAtLatestData = (visibleRange.to + 60) >= latestDataTime;
            scrollToRealtimeBtn.style.display = isAtLatestData ? 'none' : 'block';
            
        } catch (e) {
            scrollToRealtimeBtn.style.display = 'none';
        }
    };
    
    // Create scroll to realtime button
    const scrollToRealtimeBtn = document.createElement('button');
    scrollToRealtimeBtn.innerHTML = '&raquo;';
    Object.assign(scrollToRealtimeBtn.style, {
        position: 'absolute', right: '60px', bottom: '35px', zIndex: '3',
        fontSize: '14px', fontFamily: 'monospace', fontWeight: 'bold',
        padding: '4px 8px', borderRadius: '3px', border: 'none',
        backgroundColor: '#363C4E', color: '#B2B5BE', cursor: 'pointer',
        display: 'none', transition: 'all 0.2s ease', opacity: '0.9',
        minWidth: '28px', textAlign: 'center', height: '24px', lineHeight: '16px'
    });
    
    // Add hover effects and click handler
    addButtonHoverEffect(scrollToRealtimeBtn);
    scrollToRealtimeBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const chartObj = state.chartRegistry.find(obj => obj.container === container);
        if (chartObj) {
            updateChartRightOffset(chart, chartObj.chartType);
        }
        
        chart.timeScale().scrollToRealTime();
    });
    
    container.appendChild(scrollToRealtimeBtn);

    // Chart state
    let chartType = 'footprint', candlestickSeries = null, footprintSeries = null;

    // Optimized legend updater
    const updateLegend = (param) => {
        const obj = state.chartRegistry.find(o => o.container === container);
        const legendSymbol = obj?.symbol || symbol;
        const legendTimeframe = obj?.timeframe || timeframe;
        let ohlcv = '';
        // Prefer cursor-provided seriesData (when moving crosshair), otherwise fallback to last known candle on chart
        let open, high, low, close, volume, delta, cum_delta;
        let usedCursorData = false;
        if (param?.seriesData && param.seriesData instanceof Map) {
            const data = param.seriesData.get(candlestickSeries) || param.seriesData.get(obj?.candlestickSeries);
            if (data) {
                ({ open, high, low, close, volume, delta, cum_delta } = data);
                usedCursorData = true;
            }
        }

        if (open === undefined && obj && obj.latestCandle) {
            const lc = obj.latestCandle;
            open = lc.open; high = lc.high; low = lc.low; close = lc.close; volume = lc.volume; delta = lc.delta; cum_delta = lc.cum_delta;
        }

        if (open !== undefined) {
            const fmt = (v) => (typeof v === 'number' ? v.toFixed(2) : '');
            // Determine up/down based on close vs open
            const isUp = (typeof close === 'number' && typeof open === 'number') ? (close >= open) : null;
            const priceColor = isUp === null ? '#B2B5BE' : (isUp ? '#089981' : '#F23645');
            const upColor = '#089981';
            const downColor = '#F23645';
            ohlcv = `<br><strong>O</strong> <span style="color:${priceColor};font-weight:600">${fmt(open)}</span> <strong>H</strong> <span style="color:${upColor}">${fmt(high)}</span> <strong>L</strong> <span style="color:${downColor}">${fmt(low)}</span> <strong>C</strong> <span style="color:${priceColor};font-weight:600">${fmt(close)}</span> <strong>V</strong> ${volume || ''}`;

            if (typeof delta === 'number') {
                const deltaColor = delta >= 0 ? '#089981' : '#F23645';
                ohlcv += ` <strong>Δ</strong> <span style="color: ${deltaColor}">${Math.abs(delta)}</span>`;
            }
            if (typeof cum_delta === 'number') {
                const cumDeltaColor = cum_delta >= 0 ? '#089981' : '#F23645';
                ohlcv += ` <strong>ΣΔ</strong> <span style="color: ${cumDeltaColor}">${Math.abs(cum_delta)}</span>`;
            }
        }
        
        // If legend was driven by cursor seriesData, mark the chart to avoid being overwritten by live updates
        try {
            if (obj) {
                if (usedCursorData) {
                    obj._isCursorLegend = true;
                    if (obj._cursorLegendTimer) clearTimeout(obj._cursorLegendTimer);
                    obj._cursorLegendTimer = setTimeout(() => { obj._isCursorLegend = false; obj._cursorLegendTimer = null; }, 800);
                }
            }
        } catch (e) { /* ignore */ }
        // Get tick size and multiplier for display
        let tickInfo = '';
        if (obj) {
            const bucketSize = obj.bucket_size || 0.05;
            const multiplier = obj.multiplier || 100;
            tickInfo = ` <span style='font-weight:400;color:#8B92A8;'>( ${bucketSize} × ${multiplier} )</span>`;
        }

        legend.innerHTML = `${legendSymbol} <span style='font-weight:400;'>-${legendTimeframe}</span>${tickInfo}${ohlcv}`;
    };

    // Optimized crosshair control
    let ctrlActive = false;
    const updateCrosshairMode = (e) => {
        if (e?.key === 'Control') {
            const newCtrlActive = e.type === 'keydown';
            if (newCtrlActive !== ctrlActive) {
                ctrlActive = newCtrlActive;
                chart.applyOptions({ crosshair: { mode: ctrlActive ? 3 : 0 } });
            }
        }
    };
    
    const handleMouseEnter = () => {
        window.addEventListener('keydown', updateCrosshairMode);
        window.addEventListener('keyup', updateCrosshairMode);
    };
    
    const handleMouseLeave = () => {
        window.removeEventListener('keydown', updateCrosshairMode);
        window.removeEventListener('keyup', updateCrosshairMode);
        if (ctrlActive) {
            ctrlActive = false;
            chart.applyOptions({ crosshair: { mode: 0 } });
        }
    };
    
    container.addEventListener('mouseenter', handleMouseEnter);
    container.addEventListener('mouseleave', handleMouseLeave);

    // Add series with optimized configuration - create separate instances for each chart
    candlestickSeries = chart.addCustomSeries(RoundedCandlestickSeries.create(), {
        upColor: '#089981', downColor: '#F23645', borderUpColor: '#089981', borderDownColor: '#F23645',
        wickUpColor: '#089981', wickDownColor: '#F23645', borderVisible: true, wickVisible: true,
        borderRadius: 2, borderWidth: 1, visible: false
    });
    
    // Create a separate footprint series instance for this chart to prevent blinking in multi-chart layouts
    footprintSeries = chart.addCustomSeries(FootprintSeries.create(), { visible: true });

    
    chart.subscribeCrosshairMove(updateLegend);
    updateLegend();

    // Subscribe to time scale changes for button visibility
    chart.timeScale().subscribeVisibleTimeRangeChange(updateScrollButtonVisibility);
    
    // Initial button state check
    setTimeout(updateScrollButtonVisibility, 500);

    // Initialize Rectangle Drawing Tool (controlled from top navbar)
    const rectangleDrawingTool = new RectangleDrawingTool(
        chart,
        candlestickSeries,
        {
            fillColor: 'rgba(100, 150, 250, 0.3)',
            previewFillColor: 'rgba(100, 150, 250, 0.15)',
            labelColor: 'rgba(100, 150, 250, 1)',
            labelTextColor: 'white',
            showLabels: false,
        symbol: symbol
        }
    );
    try { console.debug('[chart] created RectangleDrawingTool for', symbol, container.id); } catch(e){}
    try { console.log('[chart] created RectangleDrawingTool for', symbol, 'container=', container.id); } catch(e){}

    // Optimized resize handling
    let resizeTimeout;
    const resizeObserver = new ResizeObserver(() => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            if (chart && container) {
                chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
            }
        }, 16);
    });
    resizeObserver.observe(container);

    // Register chart with optimized cleanup
    // Restore settings from localStorage if available
    const chartId = container.id;
    const savedSettings = LocalStorage.loadChartSettings(chartId);
    let bucket_size = savedSettings.bucket_size, multiplier = savedSettings.multiplier;
    const chartEntry = {
        chart, candlestickSeries, footprintSeries, container, symbol, timeframe,
        bucket_size, multiplier,
        effectiveBucketSize: bucket_size * multiplier, // Calculate initial effective bucket size
        resizeObserver, legend, updateLegend, chartType, scrollToRealtimeBtn,
        rectangleDrawingTool,
        _legendThrottled: false,
        cleanup: () => {
            // Unsubscribe from live data
            LiveDataManager.unsubscribeFromSymbol(chartId);
            // Cleanup drawing tool
            if (rectangleDrawingTool) {
                rectangleDrawingTool.remove();
            }
            // Unsubscribe from time scale events
            try {
                chart.timeScale().unsubscribeVisibleTimeRangeChange(updateScrollButtonVisibility);
            } catch (e) {
                // Ignore cleanup errors
            }
            clearTimeout(resizeTimeout);
            container.removeEventListener('mouseenter', handleMouseEnter);
            container.removeEventListener('mouseleave', handleMouseLeave);
            resizeObserver.disconnect();
        }
    };
    state.chartRegistry.push(chartEntry);
    
    // Set the correct right offset for the default chart type (footprint)
    updateChartRightOffset(chart, chartType);
    
    // Read time settings from localStorage if available
    const timeSettings = LocalStorage.loadTimeSettings();
    addCustomCrosshairLabel(chart, container, timeSettings);
    
    // Load historical data first, then subscribe to live updates
    loadHistoricalData(state.chartRegistry.length - 1, symbol, timeframe, bucket_size, multiplier)
        .then((historicalData) => {
            // Extract last candle for processor seeding
            const lastCandle = historicalData && historicalData.length > 0 ? historicalData[historicalData.length - 1] : null;
            
            // After historical data is loaded (or empty), subscribe to live updates
            LiveDataManager.subscribeToSymbol(chartId, symbol, timeframe, bucket_size, multiplier, lastCandle);
            // Apply footprint options including tickSize so renderer can use it
            try {
                if (chartEntry.footprintSeries && typeof chartEntry.footprintSeries.applyOptions === 'function') {
                    chartEntry.footprintSeries.applyOptions({ tickSize: chartEntry.effectiveBucketSize });
                }
            } catch (e) { console.warn('Failed to apply footprint tickSize', e); }
        })
        .catch(error => {
            console.error('Error loading historical data:', error);
            // Still try to subscribe to live data even if historical fails
            LiveDataManager.subscribeToSymbol(chartId, symbol, timeframe, bucket_size, multiplier, null);
        });
}

// Optimized resize function with better throttling
const resizeAllCharts = () => {
    // Use RAF for smoother resizing and prevent layout thrashing
    if (!window._resizeThrottled) {
        window._resizeThrottled = true;
        requestAnimationFrame(() => {
            state.chartRegistry.forEach(obj => {
                if (obj.chart && obj.container) {
                    try {
                        const rect = obj.container.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            obj.chart.applyOptions({
                                width: Math.floor(rect.width),
                                height: Math.floor(rect.height)
                            });
                        }
                    } catch (e) {
                        console.warn('Chart resize error:', e);
                    }
                }
            });
            window._resizeThrottled = false;
        });
    }
};



// Data loading and management
async function loadHistoricalData(chartIdx, symbol, timeframe, bucket_size = 0.05, multiplier = 100) {
    try {
        const url = `/api/historical?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&bucket_size=${bucket_size}&multiplier=${multiplier}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error('Network response was not ok');
        const data = await response.json();
        console.log(`Loaded historical data for ${symbol}-${timeframe}:`, data);
        
        // Validate data
        const validData = Array.isArray(data) ? data.filter(item => 
            item && typeof item === 'object' && 
            !isNaN(item.time) && 
            !isNaN(item.open) && !isNaN(item.high) && 
            !isNaN(item.low) && !isNaN(item.close)
        ) : [];
        
        if (validData.length < (Array.isArray(data) ? data.length : 0)) {
            console.warn(`Filtered out ${(Array.isArray(data) ? data.length : 0) - validData.length} invalid data points`);
        }
        
        // Set data for both series
        const chartObj = state.chartRegistry[chartIdx];
        if (chartObj?.candlestickSeries) {
            chartObj.candlestickSeries.setData(validData);
            try { chartObj.rectangleDrawingTool?.refreshDrawings(); } catch (e) {}
            // Update legend after historical data load so UI reflects last candle
            try { chartObj.updateLegend?.({ latestCandle: chartObj.candlestickSeries.data?.()?.slice(-1)[0] || chartObj.latestCandle }); } catch (e) {}
        }
        if (chartObj?.footprintSeries) {
            chartObj.footprintSeries.setData(validData);
            if (chartObj.chartType === 'footprint') {
                chartObj.candlestickSeries.applyOptions({ visible: false });
                chartObj.footprintSeries.applyOptions({ visible: true });
            }
        }
        
        
        console.log(`Loaded ${validData.length} data points for ${symbol}-${timeframe}`);
        
        // Return the validated data for continuity context initialization
        return validData;
        
    } catch (e) {
        console.error('Error loading historical data:', e);
        return []; // Return empty array on error
    }
}

// Helper: update legends for all charts using their latestCandle or series data
function updateAllLegends() {
    state.chartRegistry.forEach((obj) => {
        if (!obj) return;
        try {
            const latest = obj.latestCandle || (obj.candlestickSeries?.data?.()?.slice(-1)[0]);
            obj.updateLegend?.({ latestCandle: latest });
        } catch (e) {
            // ignore
        }
    });
}

// Load all charts data with per-chart settings
function loadAllChartsData() {
    const chartConfigs = state.chartRegistry.map((obj, idx) => ({
        chartIdx: idx,
        symbol: obj.symbol,
        timeframe: obj.timeframe,
        bucket_size: obj.bucket_size || 0.05,
        multiplier: obj.multiplier || 100
    }));
    chartConfigs.forEach(cfg => {
        loadHistoricalData(cfg.chartIdx, cfg.symbol, cfg.timeframe, cfg.bucket_size, cfg.multiplier);
    });
}

// Centralized data loading and subscription management
const updateChartData = async (chartIdx, symbol, timeframe, bucket_size = 0.05, multiplier = 100) => {
    const obj = state.chartRegistry[chartIdx];
    if (!obj) return;
    
    console.log(`Updating chart ${chartIdx} to ${symbol}-${timeframe} (bucket: ${bucket_size}, multiplier: ${multiplier})`);
    
    // Check if we're switching timeframes for the same symbol
    const isTimeframeSwitch = (obj.symbol === symbol && obj.timeframe !== timeframe);
    
    // First, unsubscribe from current live data to prevent conflicts
    const chartId = obj.container.id;
    LiveDataManager.unsubscribeFromSymbol(chartId);
    
    // Clear processor state if switching timeframes to prevent stale data
    if (isTimeframeSwitch) {
        console.log(`Timeframe switch detected for ${symbol}: ${obj.timeframe} -> ${timeframe}`);
        try {
            await clearProcessorState(obj.symbol, obj.timeframe, obj.bucket_size, obj.multiplier);
            console.log(`Processor state cleared for ${obj.symbol}-${obj.timeframe}`);
        } catch (error) {
            console.warn('Failed to clear processor state:', error);
        }
    }
    
    // Update chart properties
    Object.assign(obj, { symbol, timeframe, bucket_size, multiplier });
    // Recreate drawing tool for new symbol so persisted drawings are reloaded
    try {
        if (obj.rectangleDrawingTool) {
            try { obj.rectangleDrawingTool.remove(); } catch (e) {}
        }
        const newTool = new RectangleDrawingTool(obj.chart, obj.candlestickSeries, {
            ...(obj.rectangleDrawingTool?._defaultOptions || {}),
            symbol: symbol
        });
    obj.rectangleDrawingTool = newTool;
    } catch (err) {
        console.warn('Failed to recreate drawing tool for symbol change', err);
    }
    
    try {
    // Load historical data
        const historicalData = await loadHistoricalData(chartIdx, symbol, timeframe, bucket_size, multiplier);
        
        // Extract last candle for processor seeding
        const lastCandle = historicalData && historicalData.length > 0 ? historicalData[historicalData.length - 1] : null;
        
    // Subscribe to live data updates with historical seeding
        LiveDataManager.subscribeToSymbol(chartId, symbol, timeframe, bucket_size, multiplier, lastCandle);
        
        // Force immediate UI update
        updateNavbarSymbolAndTimeframe();
        obj.updateLegend?.();
        
        // Apply chart type styling based on current selection
        switchChartType(obj, obj.chartType || 'candlestick');
        
        // Ensure proper chart scaling and visibility
        setTimeout(() => {
            if (obj.chart) {
                obj.chart.timeScale().fitContent();
            }
        }, 100);
        
        console.log(`Chart ${chartIdx} successfully updated to ${symbol}-${timeframe}`);
        // Notify other charts that drawings for this symbol may need to reload
        try { document.dispatchEvent(new CustomEvent('tradelab:drawings-updated', { detail: { symbol, sourceId: `chart-${chartIdx}`, ts: Date.now() } })); } catch (e) {}
        
    } catch (error) {
        console.error(`Error updating chart ${chartIdx}:`, error);
        
        // Fallback: still try to subscribe to live data even if historical fails
        LiveDataManager.subscribeToSymbol(chartId, symbol, timeframe, bucket_size, multiplier, null);
    }
    
    // Save layout after successful update
    LocalStorage.saveLayout();
};

// Clear processor state function
async function clearProcessorState(symbol, timeframe, bucket_size, multiplier) {
    try {
        const response = await fetch('/api/clear_processor_state', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                symbol,
                timeframe,
                bucket_size,
                multiplier
            })
        });
        
        if (!response.ok) {
            throw new Error('Failed to clear processor state');
        }
        
        const result = await response.json();
        console.log(`Processor state cleared:`, result);
        return result;
    } catch (error) {
        console.error('Error clearing processor state:', error);
        throw error;
    }
}

// Enhanced Symbol and timeframe management with immediate updates
const updateSymbol = async (symbol) => {
    console.log(`Global symbol change requested: ${symbol}`);
    state.currentSymbol = symbol;
    const obj = state.chartRegistry[state.selectedChartIndex];
    if (obj) {
        console.log(`Updating selected chart ${state.selectedChartIndex} to symbol: ${symbol}`);
        await updateChartData(state.selectedChartIndex, symbol, obj.timeframe, obj.bucket_size, obj.multiplier);
    }
};

const updateTimeframe = async (tf) => {
    console.log(`Global timeframe change requested: ${tf}`);
    state.currentTimeframe = tf;
    const obj = state.chartRegistry[state.selectedChartIndex];
    if (obj) {
        console.log(`Updating selected chart ${state.selectedChartIndex} to timeframe: ${tf}`);
        await updateChartData(state.selectedChartIndex, obj.symbol, tf, obj.bucket_size, obj.multiplier);
    }
};

// Function to update all charts to the same symbol (useful for synchronized analysis)
const updateAllChartsSymbol = async (symbol) => {
    console.log(`Updating all charts to symbol: ${symbol}`);
    state.currentSymbol = symbol;
    const updatePromises = state.chartRegistry.map(async (obj, idx) => {
        if (obj && obj.symbol !== symbol) {
            console.log(`Updating chart ${idx} from ${obj.symbol} to ${symbol}`);
            await updateChartData(idx, symbol, '5m', obj.bucket_size, obj.multiplier);
        }
    });
    await Promise.all(updatePromises);
    console.log('All charts updated to new symbol (5m timeframe)');
};

// Function to set different timeframes across charts (useful for multi-timeframe analysis)
// Remove multi-timeframe analysis feature
const setChartTimeframes = async (timeframes) => {
    // Disabled: always use 5m for all charts
    console.log('Multi-timeframe analysis is disabled. All charts use 5m timeframe.');
};

// Global legend updater for selected chart
const updateLegend = (param) => {
    const obj = state.chartRegistry[state.selectedChartIndex];
    if (obj?.updateLegend) obj.updateLegend(param);
};

// Settings and event handlers
document.addEventListener('settingsApplied', (event) => {
    state.timezone = event.detail.timezone || getCurrentTimezone();
    state.use12Hour = (event.detail.timeFormat || getTimeFormat()) === '12h';
    // Save settings to localStorage
    LocalStorage.saveTimeSettings(state.timezone, state.use12Hour);
    state.chartRegistry.forEach(obj => obj.chart.applyOptions({ timeScale: { tickMarkFormatter: getTickFormatter() } }));
});

// Enhanced keyboard shortcuts with timeframe switching
// Timeframe shortcut state accumulator for multi-digit ctrl sequences
let timeframeSequence = '';
let timeframeSeqTimeout = null;
let timeframeSingleDigitTimeout = null; // defers single-digit '1' to allow '11'/'15'

// Timeframe shortcut mapping and helpers
const TF_MAP = { '1': '1m', '5': '5m', '11': '1d', '15': '15m' };
const MULTI_PREFIXES = new Set(Object.keys(TF_MAP).filter(k => k.length > 1).map(k => k[0])); // e.g., '1'
const clearAllTfTimers = () => { clearTimeout(timeframeSeqTimeout); clearTimeout(timeframeSingleDigitTimeout); timeframeSeqTimeout = null; timeframeSingleDigitTimeout = null; };
const triggerTf = (tf) => { try { updateTimeframe(tf); } catch {} timeframeSequence = ''; clearAllTfTimers(); };
const resetTfSeq = () => { timeframeSequence = ''; clearAllTfTimers(); };

document.addEventListener('keydown', (e) => {
    // Existing shortcuts
    if (e.ctrlKey && e.altKey && e.key === 's') {
        e.preventDefault();
        const chartTypeBtn = document.querySelector('#chart-type-switch');
        if (chartTypeBtn) {
            const clickEvent = new MouseEvent('click', { shiftKey: true, bubbles: true });
            chartTypeBtn.dispatchEvent(clickEvent);
        }
        return;
    }
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent('chartTypeSwitch', {}));
        return;
    }

    // Toggle Volume Profile (Ctrl+F) - override browser find
    if (e.ctrlKey && !e.shiftKey && !e.altKey && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
    }

    // Toggle Side Volume Profile (Ctrl+D) - current day side profile
    if (e.ctrlKey && !e.shiftKey && !e.altKey && (e.key === 'd' || e.key === 'D')) {
    }

        // New timeframe switching shortcuts (Ctrl+1, Ctrl+5, Ctrl+15, Ctrl+11)
        if ((e.ctrlKey && !e.altKey && /^\d$/.test(e.key)) || (timeframeSequence && /^\d$/.test(e.key))) {
            // Accept digit if Ctrl is held, or if a sequence is in progress
            e.preventDefault();

            // Build/extend sequence and manage timers
            timeframeSequence += e.key;
            clearTimeout(timeframeSingleDigitTimeout); // cancel pending single-digit actions
            clearTimeout(timeframeSeqTimeout);
            timeframeSeqTimeout = setTimeout(() => { timeframeSequence = ''; }, 800);

            const seq = timeframeSequence;
            const len = seq.length;

            if (len === 1) {
                // If this single digit is a prefix to multi-digit combos, defer; else trigger immediately if mapped
                if (MULTI_PREFIXES.has(seq)) {
                    timeframeSingleDigitTimeout = setTimeout(() => {
                        if (timeframeSequence === seq) {
                            const tf = TF_MAP[seq];
                            if (tf) triggerTf(tf); // fallback to single-digit mapping if no second key
                        }
                    }, 250);
                } else {
                    const tf = TF_MAP[seq];
                    if (tf) triggerTf(tf);
                }
                return;
            }

            if (len === 2) {
                const tf = TF_MAP[seq];
                if (tf) {
                    triggerTf(tf);
                } else {
                    resetTfSeq();
                }
                return;
            }

            // If sequence grows beyond 2 digits without match, reset
            if (len > 2) {
                resetTfSeq();
            }
            return;
        }

    // Chart navigation shortcut (Tab without Ctrl)
    if (e.key === 'Tab' && !e.ctrlKey) {
        e.preventDefault();
        const nextIndex = (state.selectedChartIndex + 1) % state.chartRegistry.length;
        setSelectedChart(nextIndex);
        return;
    }

    // Multi-timeframe analysis shortcut
    if (e.ctrlKey && e.key === 'm') {
        e.preventDefault();
        // Disabled: do nothing
        return;
    }

    // Sync symbol across charts
    if (e.ctrlKey && e.key === 'y') {
        e.preventDefault();
        const currentSymbol = state.chartRegistry[state.selectedChartIndex]?.symbol;
        if (currentSymbol) {
            updateAllChartsSymbol(currentSymbol);
        }
    }

    // Toggle rectangle drawing tool
    if (e.ctrlKey && e.key === 'r') {
        e.preventDefault();
        const drawingToolBtn = document.getElementById('drawing-tool-btn');
        if (drawingToolBtn) {
            drawingToolBtn.click();
        }
    }

    // Toggle horizontal line drawing tool (Ctrl+E)
    if (e.ctrlKey && e.key === 'e') {
        e.preventDefault();
        const horizontalLineBtn = document.getElementById('horizontal-line-tool-btn');
        if (horizontalLineBtn) {
            horizontalLineBtn.click();
        }
    }
});

// Listen for chart settings changes from navbar
document.addEventListener('chartSettingsChanged', (event) => {
    const { bucket_size, multiplier } = event.detail;
    const obj = state.chartRegistry[state.selectedChartIndex];
    if (obj) {
        // Update chart object with new values
        obj.bucket_size = bucket_size;
        obj.multiplier = multiplier;
        obj.effectiveBucketSize = bucket_size * multiplier;

        // Persist settings per chart id (without imbalanceVolumeThreshold)
        LocalStorage.saveChartSettings(obj.container.id, bucket_size, multiplier);

        // Log for debugging
        console.log(`Applying footprint settings to chart ${state.selectedChartIndex}: bucket_size=${bucket_size}, multiplier=${multiplier}, effectiveBucketSize=${obj.effectiveBucketSize}`);

        // Update footprint series tickSize in real-time if footprint series exists
        try {
            if (obj.footprintSeries && typeof obj.footprintSeries.applyOptions === 'function') {
                obj.footprintSeries.applyOptions({ tickSize: obj.effectiveBucketSize });
                console.log(`Updated footprint series tickSize to ${obj.effectiveBucketSize}`);
            }
        } catch (e) {
            console.warn('Failed to update footprint tickSize', e);
        }

        // Update chart data with new settings (for data reprocessing)
        updateChartData(state.selectedChartIndex, obj.symbol, obj.timeframe, bucket_size, multiplier);
    }
});

// Layout button management
const setupLayoutButtonEvents = () => {
    for (let num = 1; num <= 5; num++) {
        const btn = document.getElementById(`layout-${num}`);
        if (btn) {
            btn.onclick = () => {
                // layout-5 is our special split-right variant (3 charts)
                if (num === 5) {
                    setLayout(3, 'split-right');
                    updateLayoutButtonHighlight(5);
                } else {
                    setLayout(num);
                    updateLayoutButtonHighlight(num);
                }
            };
        }
    }

    // Allow external components (navbar) to request layout variants
    document.addEventListener('requestLayoutVariant', (e) => {
        const { numCharts, variant } = e.detail || {};
        if (!numCharts) return;
        setLayout(numCharts, variant || null);
        // highlight mapping: if variant === 'split-right' and numCharts===3 highlight layout-5
        if (variant === 'split-right' && numCharts === 3) {
            updateLayoutButtonHighlight(5);
        } else {
            updateLayoutButtonHighlight(numCharts);
        }
    });
};

const updateLayoutButtonHighlight = (activeNum) => {
    for (let num = 1; num <= 5; num++) {
        document.getElementById(`layout-${num}`)?.classList.toggle('active', num === activeNum);
    }
};

// Chart type switching
document.addEventListener('chartTypeSwitch', () => {
    const obj = state.chartRegistry[state.selectedChartIndex];
    if (!obj) return;
    
    const newType = obj.chartType === 'candlestick' ? 'footprint' : 'candlestick';
    switchChartType(obj, newType);
    obj.updateLegend?.();
    // Drawing primitives depend on series/scale; refresh to avoid missing visuals
    try { obj.rectangleDrawingTool?.refreshDrawings(); } catch (e) {}
    setSelectedChart(state.selectedChartIndex);
    LocalStorage.saveLayout();
});

// Initialize app
enhanceNavbar({
    onSymbolSelect: updateSymbol,
    onTimeframeSelect: updateTimeframe,
    timeframes: ['1m', '5m', '15m', '1d'],
    defaultTimeframe: '5m'
});

document.addEventListener('DOMContentLoaded', () => {
    setupLayoutButtonEvents();
    
    // Initialize Socket.IO connection
    initializeSocket();
    
    // Try to load saved layout first, otherwise use default single chart layout
    const savedLayout = LocalStorage.loadLayout();
    if (savedLayout && LocalStorage.applyLayout(savedLayout)) {
        console.log('Successfully restored layout from localStorage');
    } else {
        console.log('Using default single chart layout');
        setLayout(1);
        updateLayoutButtonHighlight(1);
    }
    
    window.addEventListener('resize', resizeAllCharts);
    document.addEventListener('navbarToggled', () => setTimeout(resizeAllCharts, 320));
    
    // Cleanup live data subscriptions when page unloads
    window.addEventListener('beforeunload', () => {
        LiveDataManager.unsubscribeAll();
        if (socket) {
            socket.disconnect();
        }
    });
});