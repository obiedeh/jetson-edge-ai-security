-- Edge IDS SQLite alerts store schema
-- Append-only tables; no migrations framework required.

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,          -- ISO-8601 UTC
    attack_type TEXT    NOT NULL,          -- one of 15 ATTACK_TYPES
    severity    TEXT    NOT NULL,          -- 'low' | 'medium' | 'high' | 'critical'
    confidence  REAL    NOT NULL,          -- 0.0 – 1.0
    source      TEXT    NOT NULL DEFAULT 'replay-csv',  -- credibility badge
    model_run_id TEXT   REFERENCES model_runs(id),
    payload_json TEXT   NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS model_runs (
    id                  TEXT    PRIMARY KEY,  -- run_id from training_run.json
    started_at          TEXT    NOT NULL,
    ended_at            TEXT,
    dataset_hash        TEXT,
    training_run_hash   TEXT,
    detector_name       TEXT,
    detector_version    TEXT,
    forecaster_name     TEXT,
    forecaster_version  TEXT,
    auc                 REAL,
    f1                  REAL,
    fpr                 REAL,
    mae                 REAL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS forecast_snapshots (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at              TEXT    NOT NULL,
    model_run_id              TEXT    REFERENCES model_runs(id),
    lookback_window_seconds   INTEGER NOT NULL DEFAULT 300,
    forecast_horizon_seconds  INTEGER NOT NULL DEFAULT 30,
    payload_json              TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_alerts_timestamp     ON alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_attack_type   ON alerts(attack_type);
CREATE INDEX IF NOT EXISTS idx_alerts_severity      ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_snapshots_generated  ON forecast_snapshots(generated_at);
