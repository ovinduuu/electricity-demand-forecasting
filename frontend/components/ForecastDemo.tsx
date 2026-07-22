"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { fetchForecast, fetchHistory, fetchSeriesAccuracy, getApiBaseUrl } from "@/lib/api";
import type { ForecastPoint, HistoryPoint, SeriesAccuracyPoint, SeriesInfo } from "@/lib/types";
import SeriesPicker from "./SeriesPicker";
import ForecastChart from "./ForecastChart";

interface Props {
  initialSeries: SeriesInfo[];
  initialError: string | null;
}

export default function ForecastDemo({ initialSeries, initialError }: Props) {
  const [selected, setSelected] = useState<SeriesInfo | null>(initialSeries[0] ?? null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [forecast, setForecast] = useState<ForecastPoint | null>(null);
  const [accuracy, setAccuracy] = useState<SeriesAccuracyPoint[]>([]);
  const [error, setError] = useState<string | null>(initialError);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;

    startTransition(async () => {
      try {
        const [historyData, forecastData] = await Promise.all([
          fetchHistory(selected.ba_code, 90),
          fetchForecast(selected.ba_code),
        ]);
        if (cancelled) return;
        setHistory(historyData);
        setForecast(forecastData);
        setError(null);
      } catch (err: unknown) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load data");
      }
    });

    // Independent of the history/forecast fetch above: a BA with no
    // backfilled predictions yet shouldn't block or error the main chart.
    fetchSeriesAccuracy(selected.ba_code)
      .then((data) => {
        if (!cancelled) setAccuracy(data);
      })
      .catch(() => {
        if (!cancelled) setAccuracy([]);
      });

    return () => {
      cancelled = true;
    };
  }, [selected]);

  const seriesLabel = useMemo(
    () => (selected ? `${selected.ba_name} (${selected.ba_code})` : ""),
    [selected],
  );

  if (initialSeries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--baseline)] p-8 text-sm">
        <p className="font-medium text-[var(--text-primary)]">Backend not reachable.</p>
        <p className="mt-2 text-[var(--text-secondary)]">
          {initialError ?? "No series returned."} Trying to reach{" "}
          <code className="rounded bg-[var(--surface-1)] px-1 py-0.5">{getApiBaseUrl()}</code>.
          Set <code className="rounded bg-[var(--surface-1)] px-1 py-0.5">
            NEXT_PUBLIC_API_BASE_URL
          </code>{" "}
          to a running instance of the serving API — see{" "}
          <code className="rounded bg-[var(--surface-1)] px-1 py-0.5">frontend/README.md</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <SeriesPicker series={initialSeries} selected={selected} onSelect={setSelected} />
      {error && <p className="text-sm text-[var(--status-critical)]">{error}</p>}
      <ForecastChart
        history={history}
        forecast={forecast}
        accuracy={accuracy}
        seriesLabel={seriesLabel}
        loading={isPending}
      />
    </div>
  );
}
