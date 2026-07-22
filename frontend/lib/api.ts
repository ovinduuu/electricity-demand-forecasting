import type {
  AccuracyDailyPoint,
  ForecastPoint,
  HistoryPoint,
  ModelInfo,
  SeriesAccuracyPoint,
  SeriesInfo,
} from "./types";

// The serving API from src/electricity_demand/serving/app.py. Defaults to a
// locally-running instance - see frontend/README.md and set
// NEXT_PUBLIC_API_BASE_URL to point at the real deployed Cloud Run URL.
export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export function fetchSeries(): Promise<SeriesInfo[]> {
  return fetchJson<SeriesInfo[]>("/series");
}

export function fetchHistory(baCode: string, days = 90): Promise<HistoryPoint[]> {
  const params = new URLSearchParams({ days: String(days) });
  return fetchJson<HistoryPoint[]>(`/history/${encodeURIComponent(baCode)}?${params}`);
}

export function fetchForecast(baCode: string): Promise<ForecastPoint> {
  return fetchJson<ForecastPoint>(`/forecast/${encodeURIComponent(baCode)}`);
}

export function fetchAccuracyDaily(): Promise<AccuracyDailyPoint[]> {
  return fetchJson<AccuracyDailyPoint[]>("/accuracy");
}

export function fetchSeriesAccuracy(baCode: string): Promise<SeriesAccuracyPoint[]> {
  return fetchJson<SeriesAccuracyPoint[]>(`/accuracy/${encodeURIComponent(baCode)}`);
}

export function fetchModelInfo(): Promise<ModelInfo | null> {
  return fetchJson<ModelInfo | null>("/model-info");
}
