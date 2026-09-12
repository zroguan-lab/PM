PRAGMA foreign_keys = ON;

CREATE TABLE judgments (
  id TEXT PRIMARY KEY,
  judgment_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  thesis TEXT NOT NULL,
  evidence TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('buy','add','hold','reduce','sell','abandon')),
  confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  horizon_type TEXT NOT NULL CHECK (horizon_type IN ('7d','30d','90d','1y','custom')),
  due_date TEXT NOT NULL,
  reference_price REAL,
  benchmark TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT
);

CREATE TABLE judgment_tags (
  judgment_id TEXT NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  PRIMARY KEY (judgment_id, tag)
);

CREATE TABLE judgment_notes (
  id TEXT PRIMARY KEY,
  judgment_id TEXT NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 每次需要修改原始判断时插入完整快照；judgments 保留初次保存内容。
CREATE TABLE judgment_revisions (
  id TEXT PRIMARY KEY,
  judgment_id TEXT NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
  revision_no INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json)),
  change_reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (judgment_id, revision_no)
);

CREATE TABLE reviews (
  id TEXT PRIMARY KEY,
  judgment_id TEXT NOT NULL UNIQUE REFERENCES judgments(id) ON DELETE CASCADE,
  end_price REAL,
  actual_return REAL,
  benchmark_return REAL,
  excess_return REAL,
  outcome TEXT NOT NULL CHECK (outcome IN ('correct','partially_correct','incorrect','indeterminate')),
  result_summary TEXT NOT NULL,
  result_reason TEXT NOT NULL,
  original_thesis_valid TEXT NOT NULL,
  attribution TEXT NOT NULL CHECK (attribution IN ('skill','beta','luck','mixed')),
  right_points TEXT NOT NULL,
  wrong_points TEXT NOT NULL,
  next_change TEXT NOT NULL,
  new_rule TEXT,
  reviewed_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE review_revisions (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
  revision_no INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json)),
  change_reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (review_id, revision_no)
);

CREATE INDEX idx_judgments_due_date ON judgments(due_date);
CREATE INDEX idx_judgments_date ON judgments(judgment_date DESC);
CREATE INDEX idx_judgments_symbol ON judgments(symbol);
CREATE INDEX idx_judgments_asset_type ON judgments(asset_type);
CREATE INDEX idx_reviews_reviewed_at ON reviews(reviewed_at DESC);
