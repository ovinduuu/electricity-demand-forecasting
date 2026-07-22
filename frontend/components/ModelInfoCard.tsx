import type { ModelInfo } from "@/lib/types";

interface Props {
  info: ModelInfo | null;
}

function formatTrainedAt(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// Retraining otherwise happens entirely server-side (a daily scheduled Cloud
// Run Job) with no visible trace on the site - this makes "the model just
// retrained/improved" a concrete, checkable fact instead of something only
// evident by comparing BigQuery rows.
//
// eia_day_ahead_mape is EIA's own published day-ahead demand forecast,
// scored on the same validation window - a real benchmark this domain
// already provides (unlike M5's retail data, which had no equivalent), so
// "beats the grid operator's own forecast" is a genuine, checkable claim.
export default function ModelInfoCard({ info }: Props) {
  if (!info) return null;

  const beatsEia = info.mape_per_ba_mean < info.eia_day_ahead_mape;

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-md border border-[var(--gridline)] bg-[var(--surface-1)] px-4 py-3 text-xs text-[var(--text-secondary)]">
      <span>
        <span className="font-medium text-[var(--text-primary)]">Current model</span> · Trained{" "}
        {formatTrainedAt(info.trained_at)}
      </span>
      <span>MAPE {(info.mape_per_ba_mean * 100).toFixed(1)}%</span>
      <span>RMSE {info.rmse.toFixed(0)} MWh</span>
      <span>{info.n_train_rows.toLocaleString()} Training Rows</span>
      <span className={beatsEia ? "text-[var(--series-2)]" : undefined}>
        {beatsEia ? "Beats " : "vs. "}
        EIA&apos;s own day-ahead forecast ({(info.eia_day_ahead_mape * 100).toFixed(1)}% MAPE)
      </span>
    </div>
  );
}
