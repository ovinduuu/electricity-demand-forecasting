"use client";

import { useId, useMemo, useState } from "react";
import type { ForecastPoint, HistoryPoint, SeriesAccuracyPoint } from "@/lib/types";

interface Props {
  history: HistoryPoint[];
  forecast: ForecastPoint | null;
  // Backtested one-step-ahead predictions for the last ~3 months, dated in
  // the past (unlike `forecast`, which is the single live next-day point) -
  // plotted as a second line over the same actual-demand window so predicted
  // and actual can be compared directly. Empty until backfill_predictions.py
  // has run for this BA.
  accuracy: SeriesAccuracyPoint[];
  seriesLabel: string;
  loading: boolean;
}

interface ChartPoint {
  date: string;
  value: number;
  isForecast: boolean;
}

const WIDTH = 800;
const HEIGHT = 320;
// left: 80, not 48 - MWh demand values (e.g. "2,850,000") run 7-9 characters,
// much wider than the old retail project's unit-sales numbers ever were;
// 48px clipped the leading digits off the left edge of the SVG viewBox.
const MARGIN = { top: 24, right: 28, bottom: 36, left: 80 };
const PLOT_LEFT = MARGIN.left;
const PLOT_RIGHT = WIDTH - MARGIN.right;
const PLOT_TOP = MARGIN.top;
const PLOT_BOTTOM = HEIGHT - MARGIN.bottom;

function niceStep(roughStep: number): number {
  if (roughStep <= 0) return 1;
  const exponent = Math.floor(Math.log10(roughStep));
  const fraction = roughStep / 10 ** exponent;
  const niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return niceFraction * 10 ** exponent;
}

function niceTicks(maxValue: number, tickCount = 4): number[] {
  if (maxValue <= 0) return [0];
  const step = niceStep(maxValue / tickCount);
  const niceMax = Math.ceil(maxValue / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= niceMax + 1e-9; v += step) ticks.push(Math.round(v));
  return ticks;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function ForecastChart({
  history,
  forecast,
  accuracy,
  seriesLabel,
  loading,
}: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const gradientId = useId();

  const points: ChartPoint[] = useMemo(() => {
    const historyPoints: ChartPoint[] = history.map((h) => ({
      date: h.date,
      value: h.demand_mwh,
      isForecast: false,
    }));
    if (forecast) {
      historyPoints.push({
        date: forecast.date,
        value: forecast.predicted_demand_mwh,
        isForecast: true,
      });
    }
    return historyPoints;
  }, [history, forecast]);

  // Backtested predictions only matter for dates already shown on the
  // actual-demand line - anchor each one to that date's x position rather
  // than plotting on an independent scale.
  const dateToIndex = useMemo(() => {
    const m = new Map<string, number>();
    points.forEach((p, i) => m.set(p.date, i));
    return m;
  }, [points]);

  const predictedPoints = useMemo(
    () =>
      accuracy
        .map((a) => ({ ...a, index: dateToIndex.get(a.date) }))
        .filter((a): a is typeof a & { index: number } => a.index !== undefined)
        .sort((a, b) => a.index - b.index),
    [accuracy, dateToIndex],
  );
  const predictedByIndex = useMemo(() => {
    const m = new Map<number, SeriesAccuracyPoint>();
    predictedPoints.forEach((p) => m.set(p.index, p));
    return m;
  }, [predictedPoints]);

  // Summarizes the *entire* fetched accuracy window (not just the points
  // that land inside the visible history range) - a concrete number that
  // visibly changes when switching regions, unlike the dashed predicted
  // line which is easy to miss for a smoothly-forecast BA where it sits
  // close to the actual line.
  const seriesAccuracySummary = useMemo(() => {
    if (accuracy.length === 0) return null;
    const mae =
      accuracy.reduce(
        (sum, p) => sum + Math.abs(p.predicted_demand_mwh - p.actual_demand_mwh),
        0,
      ) / accuracy.length;
    const withNonzeroActual = accuracy.filter((p) => p.actual_demand_mwh > 0);
    const mape =
      withNonzeroActual.length > 0
        ? withNonzeroActual.reduce(
            (sum, p) =>
              sum + Math.abs(p.predicted_demand_mwh - p.actual_demand_mwh) / p.actual_demand_mwh,
            0,
          ) / withNonzeroActual.length
        : null;
    return { mae, mape, n: accuracy.length };
  }, [accuracy]);

  const maxValue = useMemo(
    () =>
      Math.max(
        1,
        ...points.map((p) => p.value),
        ...predictedPoints.map((p) => p.predicted_demand_mwh),
      ),
    [points, predictedPoints],
  );
  const ticks = useMemo(() => niceTicks(maxValue * 1.1), [maxValue]);
  const yMax = ticks[ticks.length - 1] || 1;

  const xForIndex = (index: number): number => {
    if (points.length <= 1) return (PLOT_LEFT + PLOT_RIGHT) / 2;
    return PLOT_LEFT + (index / (points.length - 1)) * (PLOT_RIGHT - PLOT_LEFT);
  };
  const yForValue = (value: number): number =>
    PLOT_BOTTOM - (value / yMax) * (PLOT_BOTTOM - PLOT_TOP);

  const actualPoints = points.filter((p) => !p.isForecast);
  const linePath = actualPoints
    .map((p, i) => `${i === 0 ? "M" : "L"} ${xForIndex(i).toFixed(1)} ${yForValue(p.value).toFixed(1)}`)
    .join(" ");
  const predictedLinePath = predictedPoints
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"} ${xForIndex(p.index).toFixed(1)} ${yForValue(p.predicted_demand_mwh).toFixed(1)}`,
    )
    .join(" ");

  const forecastIndex = points.length - 1;
  const lastActualIndex = actualPoints.length - 1;

  const handlePointerMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = event.clientX - rect.left;
    const ratio = Math.min(1, Math.max(0, relativeX / rect.width));
    const index = Math.round(ratio * (points.length - 1));
    setHoverIndex(index);
  };

  if (loading) {
    return (
      <div className="flex h-80 items-center justify-center text-sm text-[var(--text-muted)]">
        Loading…
      </div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="flex h-80 items-center justify-center text-sm text-[var(--text-muted)]">
        No data for this region yet.
      </div>
    );
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;

  return (
    <figure className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div>
          <figcaption className="text-sm font-medium text-[var(--text-secondary)]">
            Daily Demand — {seriesLabel}
          </figcaption>
          {seriesAccuracySummary && (
            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
              This Region: MAE {seriesAccuracySummary.mae.toFixed(0)} MWh
              {seriesAccuracySummary.mape !== null &&
                ` · MAPE ${(seriesAccuracySummary.mape * 100).toFixed(1)}%`}{" "}
              ({seriesAccuracySummary.n} matched days)
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setShowTable((v) => !v)}
          className="text-xs font-medium text-[var(--text-secondary)] underline hover:text-[var(--text-primary)]"
        >
          {showTable ? "Show the Chart" : "View as Table"}
        </button>
      </div>

      {showTable ? (
        <div className="max-h-80 overflow-auto rounded-md border border-[var(--gridline)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--gridline)] text-left text-[var(--text-secondary)]">
                <th className="px-3 py-2 font-medium">Date</th>
                <th className="px-3 py-2 font-medium">Demand (MWh)</th>
                <th className="px-3 py-2 font-medium">Predicted</th>
                <th className="px-3 py-2 font-medium">Type</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={p.date} className="border-b border-[var(--gridline)] last:border-0">
                  <td className="px-3 py-2 tabular-nums text-[var(--text-primary)]">{p.date}</td>
                  <td className="px-3 py-2 tabular-nums text-[var(--text-primary)]">
                    {p.value.toFixed(0)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-[var(--text-secondary)]">
                    {predictedByIndex.get(i)?.predicted_demand_mwh.toFixed(0) ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-secondary)]">
                    {p.isForecast ? "Forecast" : "Actual"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="w-full"
            role="img"
            aria-label={`Daily demand history and forecast for ${seriesLabel}`}
          >
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--series-1)" stopOpacity="0.1" />
                <stop offset="100%" stopColor="var(--series-1)" stopOpacity="0" />
              </linearGradient>
            </defs>

            {/* gridlines + y ticks */}
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={PLOT_LEFT}
                  x2={PLOT_RIGHT}
                  y1={yForValue(tick)}
                  y2={yForValue(tick)}
                  stroke="var(--gridline)"
                  strokeWidth={1}
                />
                <text
                  x={PLOT_LEFT - 8}
                  y={yForValue(tick)}
                  textAnchor="end"
                  dominantBaseline="middle"
                  className="fill-[var(--text-muted)] text-[11px] tabular-nums"
                >
                  {tick.toLocaleString()}
                </text>
              </g>
            ))}

            {/* x-axis date labels: first, middle, last actual point */}
            {[0, Math.floor((actualPoints.length - 1) / 2), lastActualIndex]
              .filter((i, idx, arr) => i >= 0 && arr.indexOf(i) === idx)
              .map((i) => (
                <text
                  key={i}
                  x={xForIndex(i)}
                  y={PLOT_BOTTOM + 20}
                  textAnchor="middle"
                  className="fill-[var(--text-muted)] text-[11px]"
                >
                  {formatDate(actualPoints[i].date)}
                </text>
              ))}

            {/* area wash under the actual line */}
            <path
              d={`${linePath} L ${xForIndex(lastActualIndex).toFixed(1)} ${PLOT_BOTTOM} L ${xForIndex(0).toFixed(1)} ${PLOT_BOTTOM} Z`}
              fill={`url(#${gradientId})`}
              stroke="none"
            />

            {/* actual line */}
            <path
              d={linePath}
              fill="none"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {/* backtested predicted line, last ~3 months */}
            {predictedPoints.length > 0 && (
              <>
                <path
                  d={predictedLinePath}
                  fill="none"
                  stroke="var(--series-2)"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                {predictedPoints.map((p) => (
                  <circle
                    key={p.date}
                    cx={xForIndex(p.index)}
                    cy={yForValue(p.predicted_demand_mwh)}
                    r={3}
                    fill="var(--series-2)"
                    stroke="var(--surface-1)"
                    strokeWidth={1.5}
                  />
                ))}
              </>
            )}

            {/* dashed connector + forecast marker */}
            {forecast && (
              <>
                <line
                  x1={xForIndex(lastActualIndex)}
                  y1={yForValue(actualPoints[lastActualIndex].value)}
                  x2={xForIndex(forecastIndex)}
                  y2={yForValue(forecast.predicted_demand_mwh)}
                  stroke="var(--series-2)"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  strokeLinecap="round"
                />
                <circle
                  cx={xForIndex(forecastIndex)}
                  cy={yForValue(forecast.predicted_demand_mwh)}
                  r={5}
                  fill="var(--series-2)"
                  stroke="var(--surface-1)"
                  strokeWidth={2}
                />
                <text
                  x={xForIndex(forecastIndex)}
                  y={yForValue(forecast.predicted_demand_mwh) - 14}
                  textAnchor="end"
                  className="fill-[var(--text-primary)] text-[12px] font-medium"
                >
                  Forecast: {forecast.predicted_demand_mwh.toFixed(0)} MWh
                </text>
              </>
            )}

            {/* hover crosshair */}
            {hovered && (
              <line
                x1={xForIndex(hoverIndex ?? 0)}
                x2={xForIndex(hoverIndex ?? 0)}
                y1={PLOT_TOP}
                y2={PLOT_BOTTOM}
                stroke="var(--baseline)"
                strokeWidth={1}
              />
            )}

            {/* hover hit area */}
            <rect
              x={PLOT_LEFT}
              y={PLOT_TOP}
              width={PLOT_RIGHT - PLOT_LEFT}
              height={PLOT_BOTTOM - PLOT_TOP}
              fill="transparent"
              onPointerMove={handlePointerMove}
              onPointerLeave={() => setHoverIndex(null)}
            />
          </svg>

          {hovered && (
            <div
              className="pointer-events-none absolute top-2 rounded-md border border-[var(--gridline)] bg-[var(--surface-1)] px-3 py-2 text-xs shadow-sm"
              style={{
                left: `${(xForIndex(hoverIndex ?? 0) / WIDTH) * 100}%`,
                transform: "translateX(-50%)",
              }}
            >
              <div className="text-[var(--text-secondary)]">{formatDate(hovered.date)}</div>
              <div className="mt-0.5 flex items-center gap-1.5 font-semibold text-[var(--text-primary)]">
                <span
                  className="inline-block h-0.5 w-3"
                  style={{
                    backgroundColor: hovered.isForecast ? "var(--series-2)" : "var(--series-1)",
                  }}
                />
                {hovered.value.toFixed(0)} MWh
                <span className="font-normal text-[var(--text-secondary)]">
                  {hovered.isForecast ? "(Forecast)" : ""}
                </span>
              </div>
              {!hovered.isForecast && predictedByIndex.has(hoverIndex ?? -1) && (
                <div className="mt-0.5 flex items-center gap-1.5 text-[var(--text-secondary)]">
                  <span
                    className="inline-block h-0.5 w-3 border-t-2 border-dashed"
                    style={{ borderColor: "var(--series-2)" }}
                  />
                  Predicted{" "}
                  {predictedByIndex.get(hoverIndex ?? -1)?.predicted_demand_mwh.toFixed(0)} MWh
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* legend */}
      <div className="flex items-center gap-4 text-xs text-[var(--text-secondary)]">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4" style={{ backgroundColor: "var(--series-1)" }} />
          Actual
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-0.5 w-4 border-t-2 border-dashed"
            style={{ borderColor: "var(--series-2)" }}
          />
          Forecast
        </span>
      </div>
    </figure>
  );
}
