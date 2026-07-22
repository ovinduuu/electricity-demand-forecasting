"use client";

import { useId, useMemo, useState } from "react";
import type { AccuracyDailyPoint } from "@/lib/types";

interface Props {
  daily: AccuracyDailyPoint[];
  loading: boolean;
}

const WIDTH = 800;
const HEIGHT = 280;
const MARGIN = { top: 24, right: 28, bottom: 36, left: 48 };
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
  for (let v = 0; v <= niceMax + 1e-9; v += step) ticks.push(v);
  return ticks;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Model accuracy over time (MAPE%), one line - a single series needs no
// legend box, the chart title names it. Days where every actual was zero
// (mape null) are skipped from the line but still selectable in the table.
export default function AccuracyChart({ daily, loading }: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const gradientId = useId();

  const points = useMemo(() => daily.filter((d) => d.mape !== null), [daily]);

  const maxMape = useMemo(
    () => Math.max(0.05, ...points.map((p) => (p.mape ?? 0) * 100)),
    [points],
  );
  const ticks = useMemo(() => niceTicks(maxMape * 1.15), [maxMape]);
  const yMax = ticks[ticks.length - 1] || 1;

  const xForIndex = (index: number): number => {
    if (points.length <= 1) return (PLOT_LEFT + PLOT_RIGHT) / 2;
    return PLOT_LEFT + (index / (points.length - 1)) * (PLOT_RIGHT - PLOT_LEFT);
  };
  const yForValue = (value: number): number =>
    PLOT_BOTTOM - (value / yMax) * (PLOT_BOTTOM - PLOT_TOP);

  const linePath = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"} ${xForIndex(i).toFixed(1)} ${yForValue((p.mape ?? 0) * 100).toFixed(1)}`,
    )
    .join(" ");

  const handlePointerMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = event.clientX - rect.left;
    const ratio = Math.min(1, Math.max(0, relativeX / rect.width));
    const index = Math.round(ratio * (points.length - 1));
    setHoverIndex(index);
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-[var(--text-muted)]">
        Loading…
      </div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-1 text-center text-sm text-[var(--text-muted)]">
        <p>No accuracy data yet.</p>
        <p>
          Shows up once a day&apos;s predictions have a matching actual - check back after the
          next daily ingest + batch-predict run.
        </p>
      </div>
    );
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;

  return (
    <figure className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <figcaption className="text-sm font-medium text-[var(--text-secondary)]">
          Forecast accuracy (MAPE, daily average)
        </figcaption>
        <button
          type="button"
          onClick={() => setShowTable((v) => !v)}
          className="text-xs font-medium text-[var(--text-secondary)] underline hover:text-[var(--text-primary)]"
        >
          {showTable ? "Show the Chart" : "View as Table"}
        </button>
      </div>

      {showTable ? (
        <div className="max-h-72 overflow-auto rounded-md border border-[var(--gridline)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--gridline)] text-left text-[var(--text-secondary)]">
                <th className="px-3 py-2 font-medium">Date</th>
                <th className="px-3 py-2 font-medium">MAPE</th>
                <th className="px-3 py-2 font-medium">MAE</th>
                <th className="px-3 py-2 font-medium">RMSE</th>
                <th className="px-3 py-2 font-medium">Predictions</th>
              </tr>
            </thead>
            <tbody>
              {daily.map((d) => (
                <tr key={d.date} className="border-b border-[var(--gridline)] last:border-0">
                  <td className="px-3 py-2 tabular-nums text-[var(--text-primary)]">{d.date}</td>
                  <td className="px-3 py-2 tabular-nums text-[var(--text-primary)]">
                    {d.mape !== null ? `${(d.mape * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-[var(--text-primary)]">
                    {d.mae.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-[var(--text-primary)]">
                    {d.rmse.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-[var(--text-secondary)]">
                    {d.n_predictions.toLocaleString()}
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
            aria-label="Model forecast accuracy (MAPE) over time"
          >
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--series-1)" stopOpacity="0.1" />
                <stop offset="100%" stopColor="var(--series-1)" stopOpacity="0" />
              </linearGradient>
            </defs>

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
                  {tick.toFixed(0)}%
                </text>
              </g>
            ))}

            {[0, Math.floor((points.length - 1) / 2), points.length - 1]
              .filter((i, idx, arr) => i >= 0 && arr.indexOf(i) === idx)
              .map((i) => (
                <text
                  key={i}
                  x={xForIndex(i)}
                  y={PLOT_BOTTOM + 20}
                  textAnchor="middle"
                  className="fill-[var(--text-muted)] text-[11px]"
                >
                  {formatDate(points[i].date)}
                </text>
              ))}

            <path
              d={`${linePath} L ${xForIndex(points.length - 1).toFixed(1)} ${PLOT_BOTTOM} L ${xForIndex(0).toFixed(1)} ${PLOT_BOTTOM} Z`}
              fill={`url(#${gradientId})`}
              stroke="none"
            />
            <path
              d={linePath}
              fill="none"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

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
              <div className="mt-0.5 font-semibold text-[var(--text-primary)]">
                MAPE {((hovered.mape ?? 0) * 100).toFixed(1)}%
              </div>
              <div className="mt-0.5 text-[var(--text-secondary)]">
                MAE {hovered.mae.toFixed(2)} · RMSE {hovered.rmse.toFixed(2)} ·{" "}
                {hovered.n_predictions.toLocaleString()} predictions
              </div>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
