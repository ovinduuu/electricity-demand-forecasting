"use client";

import { useMemo } from "react";
import type { SeriesInfo } from "@/lib/types";

interface Props {
  series: SeriesInfo[];
  selected: SeriesInfo | null;
  onSelect: (series: SeriesInfo) => void;
}

export default function SeriesPicker({ series, selected, onSelect }: Props) {
  const sorted = useMemo(
    () => [...series].sort((a, b) => a.ba_name.localeCompare(b.ba_name)),
    [series],
  );

  return (
    <div className="flex items-center gap-3">
      <label htmlFor="region-picker" className="text-sm font-medium text-[var(--text-secondary)]">
        Grid region
      </label>
      <select
        id="region-picker"
        className="rounded-md border border-[var(--baseline)] bg-[var(--surface-1)] px-3 py-2 text-sm text-[var(--text-primary)]"
        value={selected?.ba_code ?? ""}
        onChange={(event) => {
          const found = series.find((s) => s.ba_code === event.target.value);
          if (found) onSelect(found);
        }}
      >
        {sorted.map((s) => (
          <option key={s.ba_code} value={s.ba_code}>
            {s.ba_name} ({s.ba_code})
          </option>
        ))}
      </select>
    </div>
  );
}
