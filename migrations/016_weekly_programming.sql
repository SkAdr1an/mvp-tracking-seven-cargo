CREATE TABLE IF NOT EXISTS weekly_programming_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    week TEXT NOT NULL,
    file_name TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    rows_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    online_fetched_at TEXT
);
