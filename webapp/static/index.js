const loadCSVFile = async (file) => {
    // console.log(`Loading file: ${file}`);
    const res = await fetch(file);
    if (!res.ok) {
        throw new Error(`Failed to load file: ${file}`);
    }

    const resJson = await res.text();
    return resJson;
}

const loadJSONFile = async (file) => {
    // console.log(`Loading file: ${file}`);
    const res = await fetch(file);
    if (!res.ok) {
        throw new Error(`Failed to load file: ${file}`);
    }

    const resJson = await res.json();
    return resJson;
}

function toggleControl() {
    return {
      state: {
        is_on: false,
        auto: false,
        temperature: 20
      },
      init() {
        this.fetchData();
        setInterval(() => this.fetchData(), 5000);
      },
      async fetchData() {
        try {
          const response = await fetch('/static/data.json');
          const data = await response.json();
          this.state = data;
        } catch (error) {
          console.error('Error fetching data:', error);
        }
      },
      async updateData() {
        try {
          await fetch('/data', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(this.state),
          });
        } catch (error) {
          console.error('Error updating data:', error);
        }
      },
      toggle(key) {
        this.state[key] = !this.state[key];
        this.updateData();
      },
      increment(key) {
        this.state[key]++;
        this.updateData();
      },
      decrement(key) {
        this.state[key]--;
        this.updateData();
      }
    }
  }

function formatDate(date, locale = 'he-IL') {
    const day = new Intl.DateTimeFormat(locale, { day: '2-digit' }).format(date);
    const month = new Intl.DateTimeFormat(locale, { month: '2-digit' }).format(date);
    const year = new Intl.DateTimeFormat(locale, { year: 'numeric' }).format(date);

    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');

    return `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
}

const fetchData = async () => {
    const csv = await loadCSVFile('static/data.csv?_t=' + Date.now());
    
    const lines = csv.split('\n');
    // console.log(`Lines: ${lines.length}`);
    const headers = lines[0].split(',');
    let objs = [];

    // headers are: time (iso string), is_on (True, False), temperature (float
    for (let i = 1; i < lines.length; i++) {
        const obj = {};
        const values = lines[i].split(',');
        for (let j = 0; j < headers.length; j++) {
            const header = headers[j]?.trim();
            const rawValue = values[j]?.trim();
            // console.log('rawValue', rawValue);
            if (!rawValue) {
                continue;
            }
            const value = header === 'time' ? new Date(rawValue).getTime() : header === 'temperature' ? parseFloat(rawValue) : header === 'is_on' ? rawValue === 'True' : rawValue;
            // console.log('header', header, 'raw value', rawValue, 'value', value);
            obj[header] = value;
        }
        if (Object.keys(obj).length > 0) {
            objs.push(obj);
        }
    }

    return objs;
}

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

const renderChart = async () => {
    const isLandscpe = false;
    const isMobile = window.innerWidth < 400;
    const isSmallScreen = window.innerWidth < 1000;
    const isBigScreen = !isSmallScreen;

    let objs = await fetchData();

    console.log('data-point-length-', objs.length, 'innerWidth', window.innerWidth, isBigScreen);
    // console.log(objs)
    // take only the last 100 records:
    objs = isMobile ? objs.slice(-80) : isBigScreen ? objs.slice(0 - Math.max(Math.min(window.innerWidth * 0.5, objs.length), 500)) : objs.slice(-200);


    const ctx = document.getElementById('myChart');

    function getColor(value) {
        // console.log('getColor', value);
        return value ? 'green' : 'red';
    }

    const dataValues = objs.map(obj => obj.is_on);
    const pointColors = dataValues.map(value => getColor(value));

    const dataForChart = {
        labels: objs.map(obj => `${formatDate(new Date(obj.time))} - ${obj.temperature}°C`),
        datasets: [
            {
                data: !isLandscpe ? objs.map(obj => ({ x: obj.time, y: obj.temperature })) : objs.map(obj => ({ x: obj.temperature, y: obj.time })),
                backgroundColor: pointColors,
                borderColor: pointColors,
                borderWidth: 1,
                pointRadius: 2,
            }
        ]

    }

    const minTemp = Math.min(...objs.map(obj => obj.temperature));
    const maxTemp = Math.max(...objs.map(obj => obj.temperature));

    console.log('min / max date', objs[0].time, objs[objs.length - 1].time);
    console.log('min / max temperature', minTemp, maxTemp);

    const scales = {
        y: {
            beginAtZero: true,
            title: {
                display: true,
                text: 'Temperature (°C)'
            },
            min: minTemp - 3,
            max: maxTemp + 3,
            ticks: {
                callback: function (value, index, values) {
                    return `${value}°C`;
                }
            }
        },
        x: {
            type: 'time',
            min: objs[0].time,
            max: objs[objs.length - 1].time,
            title: {
                display: true,
                text: 'Time'
            }
        }

    };

    if (!window.chart) {
        const chart = new Chart(ctx, {
            type: 'scatter',
            data: dataForChart,
            options: {
                 maintainAspectRatio: false,
                // maintainAspectRatio: isSmallScreen ? false : true,
                responsive: true,
                scales: !isLandscpe ? scales : { x: scales.y, y: scales.x },
                plugins: {
                    title: {
                        display: true,
                        text: 'AYAL AC Status'
                    },
                    legend: {
                        display: false
                    }
                }
            }

        });
        window.chart = chart;
    }
    else {
        console.log('Updating chart', dataForChart.datasets[0].data.length);
        window.chart.data = dataForChart;
        window.chart.options.scales = {
            ...scales,
        }
        window.chart.update();
    }

}

window.chart = null;

(async () => {
    await renderChart();
    setInterval(async () => {
        console.log('Refreshing chart');
        await renderChart();
    }, 30000);
})();
