/* AYAL AC dashboard — Alpine component + ECharts renderer.
 * Data contract (unchanged):
 *   GET  /data            -> { is_on, auto, temperature, too_hot_temp, too_cold_temp, ac_temp }
 *   POST /data            <- the full state object
 *   GET  /history         -> CSV "time, is_on(True/False), temperature"
 *   GET  /control/on?temp=&fan=&mode=cool , GET /control/off
 */

function dashboard() {
    return {
        state: { is_on: false, auto: false, temperature: 0, ac_temp: 0, too_hot_temp: 25, too_cold_temp: 23 },
        connected: false,
        lastUpdated: '',
        busy: false,
        toastMsg: '',
        setTemp: 24,
        setFan: 'medium',
        range: 24, // hours; 0 = all
        ranges: [{ n: 1, label: '1h' }, { n: 6, label: '6h' }, { n: 24, label: '24h' }, { n: 0, label: 'All' }],
        chart: null,

        init() {
            this.fetchState();
            this.initChart();
            this.refreshChart();
            setInterval(() => this.fetchState(), 5000);
            setInterval(() => this.refreshChart(), 30000);
            window.addEventListener('resize', () => this.chart && this.chart.resize());
            this.$nextTick(() => this.icons());
        },

        icons() { if (window.lucide) lucide.createIcons(); },

        fmt(v) {
            const n = Number(v);
            if (!isFinite(n)) return '--';
            return Number.isInteger(n) ? String(n) : n.toFixed(1);
        },

        get bandLabel() {
            const t = Number(this.state.temperature);
            if (t > Number(this.state.too_hot_temp)) return 'Above upper limit';
            if (t < Number(this.state.too_cold_temp)) return 'Below lower limit';
            return 'Within comfort range';
        },
        get bandClass() {
            const t = Number(this.state.temperature);
            if (t > Number(this.state.too_hot_temp)) return 'text-orange-300';
            if (t < Number(this.state.too_cold_temp)) return 'text-sky-300';
            return 'text-green-300';
        },

        async fetchState() {
            try {
                const res = await fetch('/data', { cache: 'no-store' });
                const data = await res.json();
                if (data && Object.keys(data).length) this.state = { ...this.state, ...data };
                this.connected = true;
                const d = new Date();
                this.lastUpdated = '· ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
                this.$nextTick(() => this.icons());
            } catch (e) {
                this.connected = false;
                console.error('fetchState', e);
            }
        },

        async postState() {
            try {
                await fetch('/data', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.state),
                });
                this.refreshLimitLines();
            } catch (e) { console.error('postState', e); }
        },

        toggle(key) { this.state[key] = !this.state[key]; this.postState(); },
        increment(key) { this.state[key] = Math.round((Number(this.state[key]) + 0.5) * 2) / 2; this.postState(); },
        decrement(key) { this.state[key] = Math.round((Number(this.state[key]) - 0.5) * 2) / 2; this.postState(); },

        async control(action) {
            this.busy = true;
            try {
                const url = action === 'on'
                    ? `/control/on?temp=${this.setTemp}&fan=${this.setFan}&mode=cool`
                    : '/control/off';
                const res = await fetch(url);
                const j = await res.json().catch(() => ({}));
                this.toast(j.status === 'ok'
                    ? (action === 'on' ? `AC on · ${this.setTemp}°C · ${this.setFan}` : 'AC off')
                    : 'Command failed');
                setTimeout(() => this.fetchState(), 1500);
            } catch (e) {
                this.toast('Command failed');
            } finally { this.busy = false; }
        },

        toast(msg) {
            this.toastMsg = msg;
            this.$nextTick(() => this.icons());
            clearTimeout(this._t);
            this._t = setTimeout(() => this.toastMsg = '', 3000);
        },

        setRange(n) { this.range = n; this.refreshChart(); },

        // Robust timestamp parse. The CSV uses "YYYY-MM-DD HH:MM:SS.ffffff"
        // (space-separated, 6 fractional digits) which browsers parse
        // inconsistently via new Date() — so build it from components.
        parseTs(s) {
            if (!s) return NaN;
            const m = s.trim().match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/);
            if (!m) { const d = Date.parse(s); return isNaN(d) ? NaN : d; }
            const ms = m[7] ? parseInt(m[7].slice(0, 3).padEnd(3, '0'), 10) : 0;
            return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6], ms).getTime();
        },

        /* ---------- chart ---------- */
        initChart() {
            const el = document.getElementById('chart');
            if (!el || !window.echarts) return;
            this.chart = echarts.init(el, null, { renderer: 'canvas' });
            // Re-measure whenever the container resizes (fixes a too-narrow chart
            // when ECharts initializes before the layout/fonts settle).
            try { new ResizeObserver(() => this.chart && this.chart.resize()).observe(el); } catch (e) { }
            setTimeout(() => this.chart && this.chart.resize(), 300);
            this.chart.setOption({
                backgroundColor: 'transparent',
                grid: { left: 48, right: 18, top: 18, bottom: 36 },
                tooltip: {
                    trigger: 'axis',
                    backgroundColor: 'rgba(15,21,43,0.95)',
                    borderColor: 'rgba(255,255,255,0.1)',
                    textStyle: { color: '#e2e8f0', fontSize: 12 },
                    formatter: (ps) => {
                        if (!ps.length) return '';
                        const d = new Date(ps[0].value[0]);
                        const time = d.toLocaleString('he-IL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
                        let temp = '--', on = null;
                        ps.forEach(p => {
                            if (p.seriesName === 'Temperature') temp = p.value[1]?.toFixed(1);
                            if (p.seriesName === 'State' && p.value[2] !== undefined) on = p.value[2];
                        });
                        const badge = on === null ? '' : `<span style="color:${on ? '#4ade80' : '#94a3b8'}">● AC ${on ? 'on' : 'off'}</span>`;
                        return `<div style="font-weight:600;margin-bottom:2px">${time}</div>${temp}°C &nbsp; ${badge}`;
                    }
                },
                xAxis: {
                    type: 'time',
                    min: 'dataMin',
                    max: 'dataMax',
                    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.15)' } },
                    axisLabel: {
                        color: '#94a3b8', hideOverlap: true,
                        formatter: {
                            day: '{dd}/{MM}', hour: '{HH}:{mm}', minute: '{HH}:{mm}',
                            second: '{HH}:{mm}', none: '{HH}:{mm}',
                        },
                    },
                    splitLine: { show: false },
                },
                yAxis: {
                    type: 'value', scale: true,
                    axisLabel: { color: '#94a3b8', formatter: '{value}°' },
                    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                },
                series: [
                    {
                        name: 'Temperature', type: 'line', smooth: true, showSymbol: false,
                        lineStyle: { width: 2.5, color: '#38bdf8' },
                        areaStyle: {
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                { offset: 0, color: 'rgba(56,189,248,0.35)' },
                                { offset: 1, color: 'rgba(56,189,248,0.02)' },
                            ])
                        },
                        data: [],
                        markLine: {
                            symbol: 'none', label: { color: '#cbd5e1', fontSize: 10, formatter: '{b}' },
                            data: [
                                { name: 'Upper', yAxis: this.state.too_hot_temp, lineStyle: { color: 'rgba(251,146,60,0.7)', type: 'dashed' } },
                                { name: 'Lower', yAxis: this.state.too_cold_temp, lineStyle: { color: 'rgba(56,189,248,0.7)', type: 'dashed' } },
                            ]
                        },
                        markArea: {
                            silent: true, itemStyle: { color: 'rgba(34,197,94,0.06)' },
                            data: [[{ yAxis: this.state.too_cold_temp }, { yAxis: this.state.too_hot_temp }]]
                        },
                    },
                    {
                        name: 'State', type: 'scatter', symbolSize: 6, data: [], z: 5,
                        itemStyle: { color: (p) => (p.value[2] ? '#4ade80' : '#64748b') },
                    },
                ],
            });
        },

        refreshLimitLines() {
            if (!this.chart) return;
            this.chart.setOption({
                series: [{
                    markLine: {
                        symbol: 'none', label: { color: '#cbd5e1', fontSize: 10, formatter: '{b}' },
                        data: [
                            { name: 'Upper', yAxis: this.state.too_hot_temp, lineStyle: { color: 'rgba(251,146,60,0.7)', type: 'dashed' } },
                            { name: 'Lower', yAxis: this.state.too_cold_temp, lineStyle: { color: 'rgba(56,189,248,0.7)', type: 'dashed' } },
                        ]
                    },
                    markArea: {
                        silent: true, itemStyle: { color: 'rgba(34,197,94,0.06)' },
                        data: [[{ yAxis: this.state.too_cold_temp }, { yAxis: this.state.too_hot_temp }]]
                    },
                }]
            });
        },

        async refreshChart() {
            if (!this.chart) return;
            try {
                const res = await fetch('/history?_t=' + Date.now(), { cache: 'no-store' });
                const csv = await res.text();
                const lines = csv.split('\n');
                let rows = [];
                for (let i = 0; i < lines.length; i++) {
                    const v = lines[i].split(',');
                    if (v.length < 3) continue;
                    const t = this.parseTs(v[0]);
                    const on = v[1]?.trim() === 'True';
                    const temp = parseFloat(v[2]);
                    if (!isFinite(t) || !isFinite(temp)) continue;
                    rows.push([t, temp, on]);
                }
                if (this.range > 0 && rows.length) {
                    const cutoff = rows[rows.length - 1][0] - this.range * 3600 * 1000;
                    rows = rows.filter(r => r[0] >= cutoff);
                }
                this.chart.setOption({
                    series: [
                        { name: 'Temperature', data: rows.map(r => [r[0], r[1]]) },
                        { name: 'State', data: rows.map(r => [r[0], r[1], r[2]]) },
                    ],
                });
                this.refreshLimitLines();
            } catch (e) { console.error('refreshChart', e); }
        },
    };
}
