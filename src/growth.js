// Growth is supplied by the validated dataset. Never derive it from a filtered view.
export function windowWeeks(weeks, range) {
  const complete = weeks.filter((w) => w.completeWeek);
  const months = { "3M": 3, "6M": 6, "1Y": 12 };
  if (!months[range] || !complete.length) return complete;
  const cutoff = new Date(complete.at(-1).end + "T00:00:00Z");
  cutoff.setUTCMonth(cutoff.getUTCMonth() - months[range]);
  return complete.filter((w) => new Date(w.end + "T00:00:00Z") >= cutoff);
}

export function growthPoints(weeks, series, metric) {
  return weeks
    .filter((w) => w.completeWeek)
    .map((w, i, all) => {
      const value = w.series[series][metric];
      const previous = all[i - 1]?.series[series][metric];
      const consecutive =
        i > 0 && Date.parse(w.end) - Date.parse(all[i - 1].end) === 7 * 864e5;
      const lastFour = all.slice(Math.max(0, i - 3), i + 1);
      const meanAvailable =
        lastFour.length === 4 &&
        lastFour.every(
          (item, j) =>
            item.series[series][metric] != null &&
            (j === 0 ||
              Date.parse(item.end) - Date.parse(lastFour[j - 1].end) ===
                7 * 864e5),
        );
      return {
        end: w.end,
        value: value ?? null,
        change:
          consecutive && value != null && previous != null
            ? value - previous
            : null,
        mean: meanAvailable
          ? lastFour.reduce(
              (sum, item) => sum + item.series[series][metric],
              0,
            ) / 4
          : null,
      };
    });
}

export function growthDomain(values) {
  const finite = values.filter((v) => v != null && Number.isFinite(v));
  const low = Math.min(0, ...finite),
    high = Math.max(0, ...finite);
  const pad = Math.max((high - low) * 0.12, 2);
  return [low < 0 ? low - pad : -pad, high > 0 ? high + pad : pad];
}

export function heatColor(value) {
  if (value == null) return "#26313f";
  if (value === 0) return "#718194";
  return `rgba(${value > 0 ? "112,229,178" : "255,155,145"},${0.25 + Math.min(Math.abs(value) / 40, 1) * 0.75})`;
}
