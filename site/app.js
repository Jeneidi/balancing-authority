(() => {
  const money = (value) => `${value.toFixed(2)}%`;
  const formatDay = (day) => new Intl.DateTimeFormat("en", {month: "short", day: "numeric", timeZone: "UTC"}).format(new Date(`${day}T12:00:00Z`));
  const linePath = (points, x, y) => points.map((value, index) => `${index ? "L" : "M"}${x(index)},${y(value)}`).join(" ");
  const svgNode = (name, attrs = {}) => { const node = document.createElementNS("http://www.w3.org/2000/svg", name); Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value)); return node; };

  fetch("data/results.json")
    .then((response) => response.json())
    .then((payload) => {
      const authoritySelect = document.querySelector("#authority-select");
      const daySelect = document.querySelector("#day-select");
      const results = payload.authorities;
      results.forEach((result) => authoritySelect.add(new Option(`${result.display_name} (${result.authority})`, result.authority)));
      const average = (key) => results.reduce((sum, result) => sum + result[key], 0) / results.length;
      document.querySelector("#headline-model").textContent = money(average("model_mape"));
      document.querySelector("#headline-operator").textContent = money(average("operator_mape"));
      document.querySelector("#headline-win").textContent = money(average("win_rate"));
      document.querySelector("#headline-coverage").textContent = money(average("coverage_90"));
      document.querySelector("#headline-note").textContent = `Averages across the ${results.length} grid operators. Each forecast also comes with a range that should catch the real value 90% of the time.`;

      const selected = () => results.find((result) => result.authority === authoritySelect.value);
      const setDays = () => {
        const result = selected();
        daySelect.replaceChildren(...result.daily.map((row) => new Option(`${formatDay(row.day)}${row.event ? ` · ${row.event}` : ""}`, row.day)));
        draw(result, daySelect.value);
      };
      const draw = (result, day) => {
        const rows = result.series.filter((row) => row.day === day);
        const svg = document.querySelector("#forecast-chart");
        svg.replaceChildren();
        const pad = {left: 64, right: 20, top: 28, bottom: 44};
        const width = 960 - pad.left - pad.right;
        const height = 480 - pad.top - pad.bottom;
        const values = rows.flatMap((row) => [row.demand, row.operator_forecast, row.prediction, row.lower, row.upper]);
        const min = Math.min(...values) * .98;
        const max = Math.max(...values) * 1.02;
        const x = (index) => pad.left + (index / Math.max(rows.length - 1, 1)) * width;
        const y = (value) => pad.top + (1 - (value - min) / (max - min || 1)) * height;
        [0, .25, .5, .75, 1].forEach((ratio) => { const line = svgNode("line", {x1: pad.left, x2: pad.left + width, y1: pad.top + ratio * height, y2: pad.top + ratio * height, class: "grid"}); svg.append(line); const label = svgNode("text", {x: 8, y: pad.top + ratio * height + 4}); label.textContent = `${Math.round(max - ratio * (max - min))} MW`; svg.append(label); });
        const drawLine = (key, className) => svg.append(svgNode("path", {d: linePath(rows.map((row) => row[key]), x, y), fill: "none", "stroke-width": className === "model" ? 2.4 : 1.5, class: className}));
        drawLine("lower", "band-line"); drawLine("upper", "band-line"); drawLine("operator_forecast", "operator"); drawLine("prediction", "model"); drawLine("demand", "actual");
        [0, 6, 12, 18, 23].forEach((hour) => { const label = svgNode("text", {x: x(hour) - 12, y: 470}); label.textContent = `${String(hour).padStart(2, "0")}:00`; svg.append(label); });
        const daily = result.daily.find((row) => row.day === day);
        document.querySelector("#chart-status").textContent = `${result.authority} on ${formatDay(day)}: our forecast was off by ${money(daily.model_mape)}, the operator's by ${money(daily.operator_mape)}${daily.event ? ` (${daily.event})` : ""}.`;
        document.querySelector("#metric-authority").textContent = result.authority;
        const metrics = [["Our average error", money(result.model_mape)], ["Operator's own forecast error", money(result.operator_mape)], ["Simple method error (same hour last week)", money(result.last_week_mape)], ["Our error, give or take (likely range)", `${money(result.model_ci_low)} to ${money(result.model_ci_high)}`], ["Days we beat the operator", money(result.win_rate)], ["Hours where the real value fell inside our predicted range (goal: 90%)", money(result.coverage_90)]];
        document.querySelector("#metric-body").replaceChildren(...metrics.map(([label, value]) => { const row = document.createElement("tr"); row.innerHTML = `<td>${label}</td><td>${value}</td>`; return row; }));
      };
      authoritySelect.addEventListener("change", setDays); daySelect.addEventListener("change", () => draw(selected(), daySelect.value)); setDays();
    })
    .catch((error) => { document.querySelector("#headline-note").textContent = `The saved results could not load: ${error.message}`; });
})();
