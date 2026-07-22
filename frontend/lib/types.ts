export interface SeriesInfo {
  ba_code: string;
  ba_name: string;
}

export interface HistoryPoint {
  date: string; // YYYY-MM-DD
  demand_mwh: number;
}

export interface ForecastPoint {
  date: string; // YYYY-MM-DD
  predicted_demand_mwh: number;
}

export interface AccuracyDailyPoint {
  date: string; // YYYY-MM-DD
  n_predictions: number;
  mae: number;
  mape: number | null; // fraction, e.g. 0.03 = 3%
  rmse: number;
}

export interface SeriesAccuracyPoint {
  date: string; // YYYY-MM-DD
  predicted_demand_mwh: number;
  actual_demand_mwh: number;
}

export interface ModelInfo {
  trained_at: string; // ISO timestamp
  mape_per_ba_mean: number;
  mape: number;
  rmse: number;
  eia_day_ahead_mape: number; // EIA's own published day-ahead forecast, for comparison
  n_train_rows: number;
}
