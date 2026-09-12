import "server-only";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";
import type { JudgmentRow } from "./types";

const dataDir = path.join(process.cwd(), "data");
fs.mkdirSync(dataDir, { recursive: true });
const db = new DatabaseSync(path.join(dataDir, "investment-review.db"));
db.exec("PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;");
db.exec(`
CREATE TABLE IF NOT EXISTS judgments (
 id TEXT PRIMARY KEY, judgment_date TEXT NOT NULL, symbol TEXT NOT NULL, asset_type TEXT NOT NULL,
 thesis TEXT NOT NULL, evidence TEXT NOT NULL, decision TEXT NOT NULL, confidence INTEGER NOT NULL,
 horizon_type TEXT NOT NULL, due_date TEXT NOT NULL, reference_price REAL, benchmark TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT
);
CREATE TABLE IF NOT EXISTS judgment_tags (
 judgment_id TEXT NOT NULL REFERENCES judgments(id) ON DELETE CASCADE, tag TEXT NOT NULL,
 PRIMARY KEY (judgment_id, tag)
);
CREATE TABLE IF NOT EXISTS judgment_notes (
 id TEXT PRIMARY KEY, judgment_id TEXT NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
 content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
 id TEXT PRIMARY KEY, judgment_id TEXT NOT NULL UNIQUE REFERENCES judgments(id) ON DELETE CASCADE,
 end_price REAL, actual_return REAL, benchmark_return REAL, excess_return REAL, outcome TEXT NOT NULL,
 result_summary TEXT NOT NULL, result_reason TEXT NOT NULL, original_thesis_valid TEXT NOT NULL,
 attribution TEXT NOT NULL, right_points TEXT NOT NULL, wrong_points TEXT NOT NULL,
 next_change TEXT NOT NULL, new_rule TEXT, reviewed_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_revisions (
 id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
 revision_no INTEGER NOT NULL, snapshot_json TEXT NOT NULL, change_reason TEXT, created_at TEXT NOT NULL,
 UNIQUE(review_id, revision_no)
);
CREATE INDEX IF NOT EXISTS idx_judgments_due_date ON judgments(due_date);
CREATE INDEX IF NOT EXISTS idx_judgments_date ON judgments(judgment_date DESC);
`);

export { db };

export function listJudgments(query = "", status = "") {
  const like = `%${query.trim()}%`;
  const rows = db.prepare(`SELECT j.*, r.outcome, r.actual_return, r.excess_return,
    GROUP_CONCAT(t.tag, ', ') tags FROM judgments j
    LEFT JOIN reviews r ON r.judgment_id=j.id LEFT JOIN judgment_tags t ON t.judgment_id=j.id
    WHERE j.archived_at IS NULL AND (?='' OR j.symbol LIKE ? OR j.thesis LIKE ? OR j.evidence LIKE ? OR t.tag LIKE ?)
    GROUP BY j.id ORDER BY j.judgment_date DESC, j.created_at DESC`).all(query, like, like, like, like) as JudgmentRow[];
  if (!status) return rows;
  const today = new Date().toISOString().slice(0, 10);
  return rows.filter(r => status === "reviewed" ? !!r.outcome : status === "pending" ? !r.outcome && r.due_date <= today : !r.outcome && r.due_date > today);
}

export function getJudgment(id: string) {
  return db.prepare(`SELECT j.*, r.outcome, r.actual_return, r.excess_return,
    GROUP_CONCAT(t.tag, ', ') tags FROM judgments j LEFT JOIN reviews r ON r.judgment_id=j.id
    LEFT JOIN judgment_tags t ON t.judgment_id=j.id WHERE j.id=? GROUP BY j.id`).get(id) as JudgmentRow | undefined;
}
