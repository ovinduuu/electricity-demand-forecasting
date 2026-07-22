import { fetchAccuracyDaily, fetchModelInfo, fetchSeries } from "@/lib/api";
import type { AccuracyDailyPoint, ModelInfo, SeriesInfo } from "@/lib/types";
import ForecastDemo from "@/components/ForecastDemo";
import AccuracyChart from "@/components/AccuracyChart";
import ModelInfoCard from "@/components/ModelInfoCard";

export default async function Home() {
  let series: SeriesInfo[] = [];
  let loadError: string | null = null;
  try {
    series = await fetchSeries();
  } catch (err: unknown) {
    loadError = err instanceof Error ? err.message : "Unknown error";
  }

  // Independent of region selection, so a failure here (e.g. no predictions
  // have a matching actual yet) shouldn't block the forecast demo above it.
  let accuracy: AccuracyDailyPoint[] = [];
  try {
    accuracy = await fetchAccuracyDaily();
  } catch {
    accuracy = [];
  }

  let modelInfo: ModelInfo | null = null;
  try {
    modelInfo = await fetchModelInfo();
  } catch {
    modelInfo = null;
  }

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-8 px-6 py-12">
      <header className="flex flex-col gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">
            Electricity Demand Forecast
          </h1>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            Pick a US grid region to see recent electricity demand and the model&apos;s
            one-step-ahead forecast, benchmarked against the grid operator&apos;s own
            published day-ahead forecast.
          </p>
        </div>
        <ModelInfoCard info={modelInfo} />
      </header>
      <ForecastDemo initialSeries={series} initialError={loadError} />
      {series.length > 0 && (
        <section className="border-t border-[var(--gridline)] pt-6">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">
            Model Performance - All Regions
          </h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            How close forecasts came to actual demand, averaged across all 10 tracked grid
            regions and retrained daily - this doesn&apos;t change when you pick a different
            region above; see &quot;This Region&quot; under the chart for that.
          </p>
          <div className="mt-4">
            <AccuracyChart daily={accuracy} loading={false} />
          </div>
        </section>
      )}
    </main>
  );
}
