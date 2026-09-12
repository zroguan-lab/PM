from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import zlib

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover - exercised when optional runtime wheel is absent
    zstd = None

from .domain import ChainlinkObservation, MarketRuleVersion

NORMALIZED_ORDERBOOK_DEPTH = 20


class SQLiteStore:
    def __init__(self, path: str, read_only: bool = False) -> None:
        self.path = Path(path).resolve()
        self.raw_archive_directory = self.path.parent / f"{self.path.stem}-raw"
        self._raw_archive_connections: dict[str, sqlite3.Connection] = {}
        self.read_only = read_only
        if read_only:
            uri = f"file:{self.path.as_posix()}?mode=ro"
            self.connection = sqlite3.connect(uri, uri=True, timeout=30.0)
            self.connection.execute("PRAGMA query_only=ON")
        else:
            self.connection = sqlite3.connect(path, timeout=30.0)
            self.connection.execute("PRAGMA busy_timeout=30000")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_rule_versions (
                market_id TEXT NOT NULL,
                resolution_rule_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (market_id, resolution_rule_hash)
            );
            CREATE TABLE IF NOT EXISTS chainlink_observations (
                market_id TEXT NOT NULL,
                stream_id TEXT NOT NULL,
                report_id TEXT NOT NULL,
                source_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                twap_60s REAL NOT NULL,
                verification_status TEXT NOT NULL,
                raw_payload_hash TEXT NOT NULL,
                PRIMARY KEY (market_id, stream_id, report_id)
            );
            CREATE TABLE IF NOT EXISTS resolution_state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                rule_hash TEXT NOT NULL,
                calculated_at TEXT NOT NULL,
                start_price REAL NOT NULL,
                accumulated_price_time REAL NOT NULL,
                current_cumulative_twap REAL,
                remaining_duration REAL NOT NULL,
                required_remaining_twap REAL,
                required_future_twap_gap REAL,
                resolution_pressure REAL,
                provisional_resolution TEXT,
                resolution_confidence REAL NOT NULL,
                fraction_window_observed REAL NOT NULL,
                settlement_complete INTEGER NOT NULL,
                data_complete INTEGER NOT NULL,
                observation_count INTEGER NOT NULL,
                no_trade_reasons_json TEXT NOT NULL,
                UNIQUE(market_id, rule_hash, calculated_at)
            );
            CREATE INDEX IF NOT EXISTS idx_resolution_states_market_time
                ON resolution_state_snapshots(market_id, calculated_at);
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS polymarket_markets (
                market_id TEXT PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                condition_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                active INTEGER NOT NULL,
                closed INTEGER NOT NULL,
                up_token_id TEXT NOT NULL,
                down_token_id TEXT NOT NULL,
                rule_hash TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                synced_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                source_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                best_bid REAL,
                best_ask REAL,
                microprice REAL,
                spread REAL,
                bids_json TEXT NOT NULL,
                asks_json TEXT NOT NULL,
                book_hash TEXT,
                UNIQUE(token_id, source_timestamp, book_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_books_market_time
                ON orderbook_snapshots(market_id, received_timestamp);
            CREATE TABLE IF NOT EXISTS polymarket_clob_events (
                event_hash TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                market_id TEXT,
                condition_id TEXT,
                asset_id TEXT,
                source_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clob_events_market_time
                ON polymarket_clob_events(market_id, source_timestamp);
            CREATE INDEX IF NOT EXISTS idx_clob_events_received
                ON polymarket_clob_events(received_timestamp);
            CREATE TABLE IF NOT EXISTS polymarket_clob_event_batches (
                batch_hash TEXT PRIMARY KEY,
                first_source_timestamp TEXT NOT NULL,
                last_source_timestamp TEXT NOT NULL,
                first_received_timestamp TEXT NOT NULL,
                last_received_timestamp TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                compressed_json BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clob_batches_received
                ON polymarket_clob_event_batches(last_received_timestamp);
            CREATE TABLE IF NOT EXISTS polymarket_clob_trades (
                event_hash TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                side TEXT NOT NULL,
                fee_rate_bps REAL NOT NULL,
                transaction_hash TEXT,
                source_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clob_trades_market_time
                ON polymarket_clob_trades(market_id, source_timestamp);
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                markets_discovered INTEGER NOT NULL DEFAULT 0,
                books_saved INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS polymarket_book_poll_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                polled_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                relevant_markets INTEGER NOT NULL,
                expected_books INTEGER NOT NULL,
                received_books INTEGER NOT NULL,
                complete_markets INTEGER NOT NULL,
                books_saved INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_book_poll_runs_time
                ON polymarket_book_poll_runs(polled_at);
            CREATE TABLE IF NOT EXISTS polymarket_book_sync_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                first_detected_at TEXT NOT NULL,
                last_detected_at TEXT NOT NULL,
                recovered_at TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                last_error TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_open_book_gap_token
                ON polymarket_book_sync_gaps(token_id) WHERE recovered_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_book_gap_market_recovery
                ON polymarket_book_sync_gaps(market_id, recovered_at);
            CREATE TABLE IF NOT EXISTS binance_feature_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                source_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                spot_bid REAL NOT NULL,
                spot_ask REAL NOT NULL,
                spot_mid REAL NOT NULL,
                spot_imbalance REAL,
                futures_bid REAL NOT NULL,
                futures_ask REAL NOT NULL,
                futures_mid REAL NOT NULL,
                futures_imbalance REAL,
                basis_bps REAL NOT NULL,
                open_interest REAL NOT NULL,
                funding_rate REAL NOT NULL,
                mark_price REAL NOT NULL,
                index_price REAL NOT NULL,
                raw_json TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_binance_features_time
                ON binance_feature_snapshots(source_timestamp);
            CREATE TABLE IF NOT EXISTS binance_ws_event_batches (
                batch_hash TEXT PRIMARY KEY,
                first_source_timestamp TEXT NOT NULL,
                last_source_timestamp TEXT NOT NULL,
                first_received_timestamp TEXT NOT NULL,
                last_received_timestamp TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                compressed_json BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_binance_ws_batches_received
                ON binance_ws_event_batches(last_received_timestamp);
            CREATE TABLE IF NOT EXISTS binance_orderflow_seconds (
                source TEXT NOT NULL,
                bucket_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                buy_quantity REAL NOT NULL,
                sell_quantity REAL NOT NULL,
                buy_notional REAL NOT NULL,
                sell_notional REAL NOT NULL,
                trade_count INTEGER NOT NULL,
                last_price REAL NOT NULL,
                PRIMARY KEY(source, bucket_timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_binance_orderflow_time
                ON binance_orderflow_seconds(bucket_timestamp);
            CREATE TABLE IF NOT EXISTS binance_ws_book_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                best_bid REAL NOT NULL,
                best_ask REAL NOT NULL,
                best_bid_size REAL NOT NULL,
                best_ask_size REAL NOT NULL,
                depth_bid_size REAL NOT NULL,
                depth_ask_size REAL NOT NULL,
                update_id TEXT,
                snapshot_hash TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_binance_ws_books_source_time
                ON binance_ws_book_snapshots(source, source_timestamp);
            CREATE INDEX IF NOT EXISTS idx_binance_ws_books_source_id
                ON binance_ws_book_snapshots(source, id);
            CREATE TABLE IF NOT EXISTS binance_ws_stream_health (
                connection_name TEXT PRIMARY KEY,
                last_stream TEXT NOT NULL,
                last_source_timestamp TEXT NOT NULL,
                last_received_timestamp TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS raw_event_batch_catalog (
                source TEXT NOT NULL,
                batch_hash TEXT NOT NULL,
                archive_date TEXT NOT NULL,
                archive_path TEXT NOT NULL,
                first_source_timestamp TEXT NOT NULL,
                last_source_timestamp TEXT NOT NULL,
                first_received_timestamp TEXT NOT NULL,
                last_received_timestamp TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                codec TEXT NOT NULL,
                compressed_size INTEGER NOT NULL,
                PRIMARY KEY(source, batch_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_raw_catalog_source_received
                ON raw_event_batch_catalog(source, last_received_timestamp);
            CREATE TABLE IF NOT EXISTS chainlink_raw_reports (
                feed_id TEXT NOT NULL,
                observations_timestamp TEXT NOT NULL,
                valid_from_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                full_report TEXT NOT NULL,
                raw_payload_hash TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                PRIMARY KEY(feed_id, observations_timestamp, raw_payload_hash)
            );
            CREATE TABLE IF NOT EXISTS chainlink_rtds_events (
                raw_payload_hash TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                symbol TEXT NOT NULL,
                window_seconds INTEGER NOT NULL,
                source_timestamp TEXT NOT NULL,
                received_timestamp TEXT NOT NULL,
                exact_value TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chainlink_rtds_time
                ON chainlink_rtds_events(source_timestamp);
            CREATE TABLE IF NOT EXISTS research_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                prediction_timestamp TEXT NOT NULL,
                market_probability_up REAL,
                p_raw REAL,
                p_calibrated REAL,
                p_lower REAL,
                p_upper REAL,
                conservative_edge REAL,
                decision TEXT NOT NULL,
                no_trade_reasons_json TEXT NOT NULL,
                features_json TEXT NOT NULL,
                feature_schema_version TEXT,
                realtime_feature_version TEXT,
                model_version TEXT NOT NULL,
                UNIQUE(market_id, prediction_timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_predictions_market_time
                ON research_predictions(market_id, prediction_timestamp);
            CREATE TABLE IF NOT EXISTS research_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                prediction_timestamp TEXT NOT NULL,
                side TEXT NOT NULL,
                decision TEXT NOT NULL,
                model_probability REAL NOT NULL,
                market_probability REAL NOT NULL,
                executable_price REAL NOT NULL,
                fees_per_share REAL NOT NULL,
                normalized_stake REAL NOT NULL,
                normalized_shares REAL NOT NULL,
                expected_net_edge REAL NOT NULL,
                conservative_net_edge REAL NOT NULL,
                no_trade_reasons_json TEXT NOT NULL,
                model_version TEXT NOT NULL,
                outcome TEXT,
                realized_pnl REAL,
                settled_at TEXT,
                UNIQUE(market_id, prediction_timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_research_ledger_market
                ON research_ledger(market_id, settled_at);
            CREATE TABLE IF NOT EXISTS market_labels (
                market_id TEXT PRIMARY KEY,
                rule_hash TEXT NOT NULL,
                source TEXT NOT NULL,
                start_price REAL NOT NULL,
                final_twap REAL NOT NULL,
                outcome TEXT NOT NULL,
                observation_count INTEGER NOT NULL,
                finalized_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS resolution_reconciliations (
                market_id TEXT PRIMARY KEY,
                internal_outcome TEXT NOT NULL,
                polymarket_outcome TEXT NOT NULL,
                matches INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                market_payload_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_accounts (
                scenario TEXT PRIMARY KEY,
                starting_cash REAL NOT NULL,
                cash REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                prediction_timestamp TEXT NOT NULL,
                scenario TEXT NOT NULL,
                kind TEXT NOT NULL,
                side TEXT NOT NULL,
                limit_price REAL NOT NULL,
                requested_shares REAL NOT NULL,
                fill_probability REAL NOT NULL DEFAULT 0,
                filled_shares REAL NOT NULL DEFAULT 0,
                average_price REAL,
                estimated INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                realized_pnl REAL,
                UNIQUE(market_id, scenario)
            );
            CREATE INDEX IF NOT EXISTS idx_paper_orders_status ON paper_orders(status);
            CREATE TABLE IF NOT EXISTS capacity_snapshots (
                market_id TEXT NOT NULL,
                prediction_timestamp TEXT NOT NULL,
                side TEXT NOT NULL,
                capital REAL NOT NULL,
                executable_fraction REAL NOT NULL,
                average_price REAL NOT NULL,
                average_slippage REAL NOT NULL,
                net_edge REAL NOT NULL,
                capacity_limited INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(market_id, capital)
            );
            CREATE TABLE IF NOT EXISTS system_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                mode TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS statistical_risk_snapshots (
                timestamp TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                kill_reasons_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_runtime_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                last_attempted_markets INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        label_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(market_labels)")}
        if "label_version" not in label_columns:
            self.connection.execute(
                "ALTER TABLE market_labels ADD COLUMN label_version TEXT NOT NULL DEFAULT 'cumulative-twap-v1'"
            )
        prediction_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(research_predictions)")
        }
        if "feature_schema_version" not in prediction_columns:
            self.connection.execute(
                "ALTER TABLE research_predictions ADD COLUMN feature_schema_version TEXT"
            )
        if "realtime_feature_version" not in prediction_columns:
            self.connection.execute(
                "ALTER TABLE research_predictions ADD COLUMN realtime_feature_version TEXT"
            )
        from .training import (
            FEATURE_SCHEMA_VERSION, LEGACY_FEATURE_SCHEMA_VERSIONS, REALTIME_FEATURE_VERSION,
        )
        for version in (FEATURE_SCHEMA_VERSION, *LEGACY_FEATURE_SCHEMA_VERSIONS):
            self.connection.execute(
                """UPDATE research_predictions SET feature_schema_version=?
                WHERE feature_schema_version IS NULL AND features_json LIKE ?""",
                (version, f'%"feature_schema_version": "{version}"%'),
            )
        self.connection.execute(
            """UPDATE research_predictions SET realtime_feature_version=?
            WHERE realtime_feature_version IS NULL AND features_json LIKE ?""",
            (REALTIME_FEATURE_VERSION, f'%"realtime_feature_version": "{REALTIME_FEATURE_VERSION}"%'),
        )
        self.connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_predictions_feature_schema
            ON research_predictions(feature_schema_version, market_id)"""
        )
        self.connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_predictions_realtime_schema
            ON research_predictions(realtime_feature_version, market_id)"""
        )
        self.connection.commit()

    def save_polymarket_market(self, market: dict) -> None:
        self.connection.execute(
            """INSERT INTO polymarket_markets(
                market_id, slug, condition_id, start_time, end_time, active, closed,
                up_token_id, down_token_id, rule_hash, raw_json, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                slug=excluded.slug, condition_id=excluded.condition_id,
                start_time=excluded.start_time, end_time=excluded.end_time,
                active=excluded.active, closed=excluded.closed,
                up_token_id=excluded.up_token_id, down_token_id=excluded.down_token_id,
                rule_hash=excluded.rule_hash, raw_json=excluded.raw_json,
                synced_at=excluded.synced_at""",
            (
                market["market_id"], market["slug"], market["condition_id"],
                market["start_time"], market["end_time"], int(market["active"]),
                int(market["closed"]), market["up_token_id"], market["down_token_id"],
                market["rule_hash"], json.dumps(market["raw"], sort_keys=True),
                market["synced_at"],
            ),
        )
        self.connection.commit()

    def save_orderbook(self, market_id: str, outcome: str, book, raw: dict) -> bool:
        # Exact full-depth updates remain replayable in the raw CLOB archive.
        # The normalized table keeps the executable top levels used by models,
        # backtests and the configured <=1,000 USDC capacity study.
        normalized_bids = list(raw.get("bids", []))[:NORMALIZED_ORDERBOOK_DEPTH]
        normalized_asks = list(raw.get("asks", []))[:NORMALIZED_ORDERBOOK_DEPTH]
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO orderbook_snapshots(
                market_id, token_id, outcome, source_timestamp, received_timestamp,
                best_bid, best_ask, microprice, spread, bids_json, asks_json, book_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                market_id, book.token_id, outcome, book.timestamp.isoformat(),
                datetime.now(timezone.utc).isoformat(), book.best_bid, book.best_ask,
                book.microprice, book.spread,
                json.dumps(normalized_bids, sort_keys=True),
                json.dumps(normalized_asks, sort_keys=True), raw.get("hash") or "",
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def save_polymarket_book_poll_run(self, poll: dict) -> None:
        self.connection.execute(
            """INSERT INTO polymarket_book_poll_runs(
                polled_at, completed_at, relevant_markets, expected_books,
                received_books, complete_markets, books_saved, status, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                poll["polled_at"], poll["completed_at"], poll["relevant_markets"],
                poll["expected_books"], poll["received_books"], poll["complete_markets"],
                poll["books_saved"], poll["status"], poll.get("error"),
            ),
        )
        self.connection.commit()

    def record_polymarket_book_gap(
        self, market_id: str, token_id: str, outcome: str,
        detected_at: str, error: str,
    ) -> None:
        open_row = self.connection.execute(
            """SELECT id FROM polymarket_book_sync_gaps
            WHERE token_id=? AND recovered_at IS NULL""", (token_id,),
        ).fetchone()
        if open_row:
            self.connection.execute(
                """UPDATE polymarket_book_sync_gaps
                SET last_detected_at=?, occurrence_count=occurrence_count+1, last_error=?
                WHERE id=?""", (detected_at, error, open_row[0]),
            )
        else:
            self.connection.execute(
                """INSERT INTO polymarket_book_sync_gaps(
                market_id, token_id, outcome, first_detected_at, last_detected_at,
                recovered_at, occurrence_count, last_error
                ) VALUES (?, ?, ?, ?, ?, NULL, 1, ?)""",
                (market_id, token_id, outcome, detected_at, detected_at, error),
            )
        self.connection.commit()

    def recover_polymarket_book_gaps(self, token_id: str, recovered_at: str) -> int:
        cursor = self.connection.execute(
            """UPDATE polymarket_book_sync_gaps SET recovered_at=?
            WHERE token_id=? AND recovered_at IS NULL""",
            (recovered_at, token_id),
        )
        self.connection.commit()
        return int(cursor.rowcount)

    def polymarket_stream_tokens(self, start_iso: str, end_iso: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT market_id, condition_id, start_time, end_time, up_token_id, down_token_id
            FROM polymarket_markets WHERE end_time >= ? AND start_time <= ?
            ORDER BY start_time""", (start_iso, end_iso)
        ).fetchall()
        result: list[dict] = []
        for market_id, condition_id, start_time, end_time, up_token, down_token in rows:
            for outcome, token_id in (("UP", up_token), ("DOWN", down_token)):
                result.append({
                    "market_id": market_id, "condition_id": condition_id,
                    "start_time": start_time, "end_time": end_time,
                    "outcome": outcome, "token_id": token_id,
                })
        return result

    def save_polymarket_clob_event(self, event: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO polymarket_clob_events(
                event_hash, event_type, market_id, condition_id, asset_id,
                source_timestamp, received_timestamp, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["event_hash"], event["event_type"], event.get("market_id"),
                event.get("condition_id"), event.get("asset_id"),
                event["source_timestamp"], event["received_timestamp"],
                json.dumps(event["raw"], sort_keys=True),
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _compress_event_batch(raw: bytes) -> tuple[str, bytes]:
        if zstd is not None:
            return "zstd", zstd.ZstdCompressor(level=3).compress(raw)
        return "zlib", zlib.compress(raw, level=6)

    @staticmethod
    def _decompress_event_batch(codec: str, payload: bytes) -> bytes:
        if codec == "zstd":
            if zstd is None:
                raise RuntimeError("zstandard is required to replay this archived event batch")
            return zstd.ZstdDecompressor().decompress(payload)
        if codec == "zlib":
            return zlib.decompress(payload)
        raise ValueError(f"unsupported raw event archive codec: {codec}")

    def _raw_archive_connection(self, archive_date: str) -> tuple[sqlite3.Connection, Path]:
        if self.read_only:
            raise PermissionError("read-only store cannot create raw event archives")
        path = self.raw_archive_directory / f"{archive_date}.sqlite3"
        key = str(path)
        connection = self._raw_archive_connections.get(key)
        if connection is None:
            self.raw_archive_directory.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """CREATE TABLE IF NOT EXISTS event_batches (
                    source TEXT NOT NULL,
                    batch_hash TEXT NOT NULL,
                    first_source_timestamp TEXT NOT NULL,
                    last_source_timestamp TEXT NOT NULL,
                    first_received_timestamp TEXT NOT NULL,
                    last_received_timestamp TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    codec TEXT NOT NULL,
                    compressed_json BLOB NOT NULL,
                    PRIMARY KEY(source, batch_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_archive_source_received
                    ON event_batches(source, last_received_timestamp);"""
            )
            self._raw_archive_connections[key] = connection
        return connection, path

    def _save_raw_event_batch(self, source: str, events: list[dict]) -> int:
        if not events:
            return 0
        ordered_hashes = [str(item["event_hash"]) for item in events]
        batch_hash = sha256(json.dumps(ordered_hashes, separators=(",", ":")).encode()).hexdigest()
        source_times = [str(item["source_timestamp"]) for item in events]
        received_times = [str(item["received_timestamp"]) for item in events]
        last_received = max(received_times)
        archive_date = datetime.fromisoformat(last_received.replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).date().isoformat()
        raw = json.dumps(events, sort_keys=True, separators=(",", ":")).encode()
        codec, compressed = self._compress_event_batch(raw)
        archive, archive_path = self._raw_archive_connection(archive_date)
        archive_cursor = archive.execute(
            """INSERT OR IGNORE INTO event_batches(
                source, batch_hash, first_source_timestamp, last_source_timestamp,
                first_received_timestamp, last_received_timestamp, event_count,
                codec, compressed_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source, batch_hash, min(source_times), max(source_times), min(received_times),
                last_received, len(events), codec, sqlite3.Binary(compressed),
            ),
        )
        archive.commit()
        relative_path = archive_path.relative_to(self.path.parent).as_posix()
        catalog_cursor = self.connection.execute(
            """INSERT OR IGNORE INTO raw_event_batch_catalog(
                source, batch_hash, archive_date, archive_path,
                first_source_timestamp, last_source_timestamp,
                first_received_timestamp, last_received_timestamp,
                event_count, codec, compressed_size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source, batch_hash, archive_date, relative_path,
                min(source_times), max(source_times), min(received_times), last_received,
                len(events), codec, len(compressed),
            ),
        )
        self.connection.commit()
        return len(events) if archive_cursor.rowcount > 0 or catalog_cursor.rowcount > 0 else 0

    def _load_raw_event_batch(self, source: str, batch_hash: str) -> list[dict]:
        row = self.connection.execute(
            """SELECT archive_path, codec FROM raw_event_batch_catalog
            WHERE source=? AND batch_hash=?""", (source, batch_hash)
        ).fetchone()
        if row is None:
            return []
        path = self.path.parent / str(row[0])
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        archive = sqlite3.connect(uri, uri=True)
        try:
            payload = archive.execute(
                """SELECT codec, compressed_json FROM event_batches
                WHERE source=? AND batch_hash=?""", (source, batch_hash)
            ).fetchone()
        finally:
            archive.close()
        if payload is None:
            raise FileNotFoundError(f"raw event batch missing from archive: {source}/{batch_hash}")
        return json.loads(self._decompress_event_batch(str(payload[0]), payload[1]).decode("utf-8"))

    def save_polymarket_clob_event_batch(self, events: list[dict]) -> int:
        return self._save_raw_event_batch("POLYMARKET_CLOB", events)

    def load_polymarket_clob_event_batch(self, batch_hash: str) -> list[dict]:
        row = self.connection.execute(
            "SELECT compressed_json FROM polymarket_clob_event_batches WHERE batch_hash=?", (batch_hash,)
        ).fetchone()
        if row is None:
            return self._load_raw_event_batch("POLYMARKET_CLOB", batch_hash)
        return json.loads(zlib.decompress(row[0]).decode("utf-8"))

    def save_polymarket_clob_trade(self, trade: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO polymarket_clob_trades(
                event_hash, market_id, condition_id, asset_id, outcome,
                price, size, side, fee_rate_bps, transaction_hash,
                source_timestamp, received_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade["event_hash"], trade["market_id"], trade["condition_id"],
                trade["asset_id"], trade["outcome"], trade["price"], trade["size"],
                trade["side"], trade["fee_rate_bps"], trade.get("transaction_hash"),
                trade["source_timestamp"], trade["received_timestamp"],
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def recent_polymarket_trades(self, market_id: str, after_iso: str, before_iso: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT outcome, side, price, size, fee_rate_bps, source_timestamp
            FROM polymarket_clob_trades
            WHERE market_id=? AND source_timestamp>=? AND source_timestamp<=?
            ORDER BY source_timestamp""", (market_id, after_iso, before_iso)
        ).fetchall()
        names = ("outcome", "side", "price", "size", "fee_rate_bps", "source_timestamp")
        return [dict(zip(names, row)) for row in rows]

    def latest_polymarket_clob_event_at(self) -> str | None:
        row = self.connection.execute(
            """SELECT received_timestamp FROM (
                SELECT received_timestamp FROM polymarket_clob_events
                UNION ALL SELECT last_received_timestamp FROM polymarket_clob_event_batches
                UNION ALL SELECT last_received_timestamp FROM raw_event_batch_catalog
                    WHERE source='POLYMARKET_CLOB'
            ) ORDER BY received_timestamp DESC LIMIT 1"""
        ).fetchone()
        return str(row[0]) if row else None

    def save_binance_ws_event_batch(self, events: list[dict]) -> int:
        """Persist an exact, compressed batch of public Binance WS messages."""
        return self._save_raw_event_batch("BINANCE_WS", events)

    def load_binance_ws_event_batch(self, batch_hash: str) -> list[dict]:
        row = self.connection.execute(
            "SELECT compressed_json FROM binance_ws_event_batches WHERE batch_hash=?", (batch_hash,)
        ).fetchone()
        if row is None:
            return self._load_raw_event_batch("BINANCE_WS", batch_hash)
        return json.loads(zlib.decompress(row[0]).decode("utf-8"))

    def upsert_binance_orderflow_second(self, flow: dict) -> None:
        """Add a disjoint in-memory trade aggregate to its exchange-time second."""
        self.connection.execute(
            """INSERT INTO binance_orderflow_seconds(
                source, bucket_timestamp, received_timestamp, buy_quantity,
                sell_quantity, buy_notional, sell_notional, trade_count, last_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, bucket_timestamp) DO UPDATE SET
                received_timestamp=MAX(received_timestamp, excluded.received_timestamp),
                buy_quantity=buy_quantity + excluded.buy_quantity,
                sell_quantity=sell_quantity + excluded.sell_quantity,
                buy_notional=buy_notional + excluded.buy_notional,
                sell_notional=sell_notional + excluded.sell_notional,
                trade_count=trade_count + excluded.trade_count,
                last_price=excluded.last_price""",
            (
                flow["source"], flow["bucket_timestamp"], flow["received_timestamp"],
                flow["buy_quantity"], flow["sell_quantity"], flow["buy_notional"],
                flow["sell_notional"], flow["trade_count"], flow["last_price"],
            ),
        )
        self.connection.commit()

    def recent_binance_orderflow(self, after_iso: str, before_iso: str) -> dict[str, dict]:
        rows = self.connection.execute(
            """SELECT source, SUM(buy_quantity), SUM(sell_quantity),
            SUM(buy_notional), SUM(sell_notional), SUM(trade_count), MAX(last_price)
            FROM binance_orderflow_seconds
            WHERE bucket_timestamp>=? AND bucket_timestamp<=? GROUP BY source""",
            (after_iso, before_iso),
        ).fetchall()
        return {
            str(row[0]): {
                "buy_quantity": float(row[1] or 0), "sell_quantity": float(row[2] or 0),
                "buy_notional": float(row[3] or 0), "sell_notional": float(row[4] or 0),
                "trade_count": int(row[5] or 0), "last_price": float(row[6] or 0),
            }
            for row in rows
        }

    def save_binance_ws_book_snapshot(self, snapshot: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO binance_ws_book_snapshots(
                source, source_timestamp, received_timestamp, best_bid, best_ask,
                best_bid_size, best_ask_size, depth_bid_size, depth_ask_size,
                update_id, snapshot_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot["source"], snapshot["source_timestamp"], snapshot["received_timestamp"],
                snapshot["best_bid"], snapshot["best_ask"], snapshot["best_bid_size"],
                snapshot["best_ask_size"], snapshot["depth_bid_size"],
                snapshot["depth_ask_size"], snapshot.get("update_id"), snapshot["snapshot_hash"],
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def latest_binance_ws_books(self) -> dict[str, dict]:
        rows = self.connection.execute(
            """SELECT source, source_timestamp, received_timestamp, best_bid, best_ask,
            best_bid_size, best_ask_size, depth_bid_size, depth_ask_size, update_id
            FROM binance_ws_book_snapshots b
            INNER JOIN (
                SELECT source AS latest_source, MAX(id) AS latest_id
                FROM binance_ws_book_snapshots GROUP BY source
            ) latest ON b.id=latest.latest_id AND b.source=latest.latest_source"""
        ).fetchall()
        names = (
            "source", "source_timestamp", "received_timestamp", "best_bid", "best_ask",
            "best_bid_size", "best_ask_size", "depth_bid_size", "depth_ask_size", "update_id",
        )
        return {str(row[0]): dict(zip(names, row)) for row in rows}

    def latest_binance_ws_event_at(self) -> str | None:
        row = self.connection.execute(
            """SELECT last_received_timestamp FROM (
                SELECT last_received_timestamp FROM binance_ws_event_batches
                UNION ALL SELECT last_received_timestamp FROM raw_event_batch_catalog
                    WHERE source='BINANCE_WS'
            ) ORDER BY last_received_timestamp DESC LIMIT 1"""
        ).fetchone()
        return str(row[0]) if row else None

    def update_binance_ws_stream_health(self, health: dict) -> None:
        self.connection.execute(
            """INSERT INTO binance_ws_stream_health(
                connection_name, last_stream, last_source_timestamp,
                last_received_timestamp, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(connection_name) DO UPDATE SET
                last_stream=excluded.last_stream,
                last_source_timestamp=excluded.last_source_timestamp,
                last_received_timestamp=excluded.last_received_timestamp,
                updated_at=excluded.updated_at""",
            (
                health["connection_name"], health["last_stream"],
                health["last_source_timestamp"], health["last_received_timestamp"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()

    def binance_ws_stream_health(self) -> dict[str, dict]:
        rows = self.connection.execute(
            """SELECT connection_name, last_stream, last_source_timestamp,
            last_received_timestamp, updated_at FROM binance_ws_stream_health"""
        ).fetchall()
        names = (
            "connection_name", "last_stream", "last_source_timestamp",
            "last_received_timestamp", "updated_at",
        )
        return {str(row[0]): dict(zip(names, row)) for row in rows}

    def set_system_state(self, mode: str, reasons: list[str]) -> None:
        self.connection.execute(
            """INSERT INTO system_state(singleton, mode, reasons_json, updated_at)
            VALUES (1, ?, ?, ?) ON CONFLICT(singleton) DO UPDATE SET
            mode=excluded.mode, reasons_json=excluded.reasons_json, updated_at=excluded.updated_at""",
            (mode, json.dumps(sorted(set(reasons))), datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def save_statistical_risk_snapshot(self, snapshot: dict, kill_reasons: list[str]) -> None:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.connection.execute(
            """INSERT OR REPLACE INTO statistical_risk_snapshots(
                timestamp, snapshot_json, kill_reasons_json
            ) VALUES (?, ?, ?)""",
            (timestamp, json.dumps(snapshot, sort_keys=True), json.dumps(kill_reasons)),
        )
        self.connection.commit()

    def latest_statistical_risk_snapshot(self) -> dict | None:
        row = self.connection.execute(
            """SELECT timestamp, snapshot_json, kill_reasons_json
            FROM statistical_risk_snapshots ORDER BY timestamp DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        return {"timestamp": row[0], "snapshot": json.loads(row[1]), "kill_reasons": json.loads(row[2])}

    def get_last_model_attempt(self) -> int:
        row = self.connection.execute(
            "SELECT last_attempted_markets FROM model_runtime_state WHERE singleton=1"
        ).fetchone()
        return int(row[0]) if row else -1

    def set_last_model_attempt(self, independent_markets: int) -> None:
        self.connection.execute(
            """INSERT INTO model_runtime_state(singleton, last_attempted_markets, updated_at)
            VALUES (1, ?, ?) ON CONFLICT(singleton) DO UPDATE SET
            last_attempted_markets=excluded.last_attempted_markets,
            updated_at=excluded.updated_at""",
            (independent_markets, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def recent_model_evaluation_rows(self, market_limit: int = 300) -> list[dict]:
        rows = self.connection.execute(
            """SELECT p.market_id, p.p_calibrated, p.market_probability_up,
            p.features_json, l.outcome
            FROM research_predictions p
            INNER JOIN market_labels l ON l.market_id=p.market_id
            INNER JOIN resolution_reconciliations r ON r.market_id=p.market_id AND r.matches=1
            WHERE p.p_calibrated IS NOT NULL AND p.market_id IN (
                SELECT m.market_id FROM polymarket_markets m
                INNER JOIN resolution_reconciliations rr ON rr.market_id=m.market_id AND rr.matches=1
                ORDER BY m.end_time DESC LIMIT ?
            ) ORDER BY p.market_id, p.prediction_timestamp""", (market_limit,)
        ).fetchall()
        return [{
            "market_id": row[0], "model_probability": float(row[1]),
            "market_probability": float(row[2]), "features": json.loads(row[3]),
            "outcome": 1 if row[4] == "UP" else 0,
        } for row in rows]

    def recent_settled_market_pnls(self, market_limit: int = 200, scenario: str = "CONSERVATIVE") -> list[float]:
        rows = self.connection.execute(
            """SELECT market_id, SUM(realized_pnl) pnl, MAX(updated_at) settled_at
            FROM paper_orders WHERE scenario=? AND status='SETTLED'
            GROUP BY market_id ORDER BY settled_at DESC LIMIT ?""", (scenario, market_limit)
        ).fetchall()
        return [float(row[1]) for row in reversed(rows)]

    def get_system_state(self) -> dict:
        row = self.connection.execute(
            "SELECT mode, reasons_json, updated_at FROM system_state WHERE singleton=1"
        ).fetchone()
        if not row:
            return {"mode": "DISARMED", "reasons": ["state_not_initialized"], "updated_at": None}
        return {"mode": row[0], "reasons": json.loads(row[1]), "updated_at": row[2]}

    def start_sync_run(self, stale_after_seconds: float = 120.0) -> int:
        started_at = datetime.now(timezone.utc).isoformat()
        stale_before = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        self.connection.execute(
            """UPDATE sync_runs SET completed_at=?, status='INTERRUPTED',
            error=COALESCE(error, 'process stopped before sync completed')
            WHERE status='RUNNING' AND started_at < ?""",
            (started_at, stale_before),
        )
        cursor = self.connection.execute(
            "INSERT INTO sync_runs(started_at, status) VALUES (?, 'RUNNING')",
            (started_at,),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_sync_run(self, run_id: int, status: str, markets: int, books: int, error: str | None = None) -> None:
        self.connection.execute(
            """UPDATE sync_runs SET completed_at=?, status=?, markets_discovered=?,
            books_saved=?, error=? WHERE id=?""",
            (datetime.now(timezone.utc).isoformat(), status, markets, books, error, run_id),
        )
        self.connection.commit()

    def sync_status(self) -> dict:
        now = datetime.now(timezone.utc)
        relevant_start = (now - timedelta(seconds=15)).isoformat()
        relevant_end = (now + timedelta(minutes=5)).isoformat()
        rolling_book_start = (now - timedelta(minutes=30)).isoformat()
        daily_book_start = (now - timedelta(hours=24)).isoformat()
        market_count = self.connection.execute("SELECT COUNT(*) FROM polymarket_markets").fetchone()[0]
        book_count = self.connection.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0]
        relevant_market_rows = self.connection.execute(
            """SELECT m.market_id, m.slug,
            (SELECT MAX(received_timestamp) FROM orderbook_snapshots b
                WHERE b.market_id=m.market_id AND b.outcome='UP') AS up_received,
            (SELECT MAX(received_timestamp) FROM orderbook_snapshots b
                WHERE b.market_id=m.market_id AND b.outcome='DOWN') AS down_received
            FROM polymarket_markets m
            WHERE m.end_time >= ? AND m.start_time <= ?
            ORDER BY m.start_time""",
            (relevant_start, relevant_end),
        ).fetchall()
        complete_relevant_books = [
            row for row in relevant_market_rows
            if row[2] is not None and row[3] is not None
        ]
        latest_complete_book_at = None
        if complete_relevant_books:
            latest_complete_book_at = max(min(row[2], row[3]) for row in complete_relevant_books)
        def book_poll_window(start: str | None = None):
            query = """SELECT COUNT(*),
            COALESCE(SUM(CASE WHEN status='SUCCEEDED' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(expected_books), 0), COALESCE(SUM(received_books), 0),
            COALESCE(SUM(relevant_markets), 0), COALESCE(SUM(complete_markets), 0),
            MAX(completed_at), MIN(polled_at)
            FROM polymarket_book_poll_runs"""
            if start is None:
                return self.connection.execute(query).fetchone()
            return self.connection.execute(
                f"{query} WHERE polled_at >= ?", (start,),
            ).fetchone()

        rolling_book_poll = book_poll_window(rolling_book_start)
        daily_book_poll = book_poll_window(daily_book_start)
        lifetime_book_poll = book_poll_window()
        book_gap_stats = self.connection.execute(
            """SELECT COUNT(*),
            COALESCE(SUM(CASE WHEN recovered_at IS NULL THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN recovered_at IS NOT NULL THEN 1 ELSE 0 END), 0),
            MIN(CASE WHEN recovered_at IS NULL THEN first_detected_at END)
            FROM polymarket_book_sync_gaps"""
        ).fetchone()
        relevant_open_book_gaps = self.connection.execute(
            """SELECT COUNT(*) FROM polymarket_book_sync_gaps g
            INNER JOIN polymarket_markets m ON m.market_id=g.market_id
            WHERE g.recovered_at IS NULL AND m.end_time >= ? AND m.start_time <= ?""",
            (relevant_start, relevant_end),
        ).fetchone()[0]

        def poll_metrics(row, suffix: str) -> dict:
            return {
                f"polymarket_book_poll_runs_{suffix}": int(row[0] or 0),
                f"polymarket_book_poll_success_rate_{suffix}": (
                    float(row[1]) / float(row[0]) if row[0] else None
                ),
                f"polymarket_book_fetch_coverage_{suffix}": (
                    float(row[3]) / float(row[2]) if row[2] else None
                ),
                f"polymarket_complete_market_rate_{suffix}": (
                    float(row[5]) / float(row[4]) if row[4] else None
                ),
            }
        latest = self.connection.execute(
            """SELECT started_at, completed_at, status, markets_discovered,
            books_saved, error FROM sync_runs ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        feature_count = self.connection.execute("SELECT COUNT(*) FROM binance_feature_snapshots").fetchone()[0]
        prediction_count = self.connection.execute("SELECT COUNT(*) FROM research_predictions").fetchone()[0]
        label_count = self.connection.execute("SELECT COUNT(*) FROM market_labels").fetchone()[0]
        reconciled_label_count = self.connection.execute(
            "SELECT COUNT(*) FROM resolution_reconciliations WHERE matches=1"
        ).fetchone()[0]
        reconciliation_mismatches = self.connection.execute(
            "SELECT COUNT(*) FROM resolution_reconciliations WHERE matches=0"
        ).fetchone()[0]
        from .training import (
            FEATURE_SCHEMA_VERSION, LEGACY_FEATURE_SCHEMA_VERSIONS, REALTIME_FEATURE_VERSION,
        )
        schema_versions = (FEATURE_SCHEMA_VERSION, *LEGACY_FEATURE_SCHEMA_VERSIONS)
        training_ready_markets = self.connection.execute(
            """SELECT COUNT(DISTINCT p.market_id) FROM research_predictions p
            INNER JOIN resolution_reconciliations r ON r.market_id=p.market_id AND r.matches=1
            WHERE p.market_probability_up IS NOT NULL
            AND p.feature_schema_version IN (?, ?)""",
            schema_versions,
        ).fetchone()[0]
        realtime_training_ready_markets = self.connection.execute(
            """SELECT COUNT(DISTINCT p.market_id) FROM research_predictions p
            INNER JOIN resolution_reconciliations r ON r.market_id=p.market_id AND r.matches=1
            WHERE p.market_probability_up IS NOT NULL
            AND p.realtime_feature_version=?""",
            (REALTIME_FEATURE_VERSION,),
        ).fetchone()[0]
        fee_rule_count = self.connection.execute(
            "SELECT COUNT(*) FROM market_rule_versions WHERE payload_json LIKE '%base_fee%'"
        ).fetchone()[0]
        paper_order_count = self.connection.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0]
        paper_pnl = self.connection.execute("SELECT COALESCE(SUM(realized_pnl), 0) FROM paper_orders").fetchone()[0]
        capacity_count = self.connection.execute("SELECT COUNT(*) FROM capacity_snapshots").fetchone()[0]
        research_ledger_count = self.connection.execute("SELECT COUNT(*) FROM research_ledger").fetchone()[0]
        research_ledger_settled = self.connection.execute(
            "SELECT COUNT(*) FROM research_ledger WHERE settled_at IS NOT NULL"
        ).fetchone()[0]
        research_ledger_settled_markets = self.connection.execute(
            "SELECT COUNT(DISTINCT market_id) FROM research_ledger WHERE settled_at IS NOT NULL"
        ).fetchone()[0]
        research_ledger_pnl = self.connection.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM research_ledger"
        ).fetchone()[0]
        chainlink_raw_event_count = self.connection.execute("SELECT COUNT(*) FROM chainlink_rtds_events").fetchone()[0]
        chainlink_observation_count = self.connection.execute(
            "SELECT COUNT(*) FROM chainlink_observations WHERE verification_status='VERIFIED'"
        ).fetchone()[0]
        latest_chainlink = self.connection.execute(
            "SELECT source_timestamp FROM chainlink_observations WHERE verification_status='VERIFIED' ORDER BY source_timestamp DESC LIMIT 1"
        ).fetchone()
        resolution_state_stats = self.connection.execute(
            """SELECT COUNT(*), MAX(calculated_at),
            SUM(CASE WHEN data_complete=0 THEN 1 ELSE 0 END)
            FROM resolution_state_snapshots"""
        ).fetchone()
        latest_feature = self.connection.execute(
            "SELECT source_timestamp, received_timestamp FROM binance_feature_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        clob_legacy_event_count = self.connection.execute("SELECT COUNT(*) FROM polymarket_clob_events").fetchone()[0]
        clob_batch_event_count = self.connection.execute(
            "SELECT COALESCE(SUM(event_count), 0) FROM polymarket_clob_event_batches"
        ).fetchone()[0]
        clob_archive_event_count = self.connection.execute(
            """SELECT COALESCE(SUM(event_count), 0) FROM raw_event_batch_catalog
            WHERE source='POLYMARKET_CLOB'"""
        ).fetchone()[0]
        clob_event_count = clob_legacy_event_count + clob_batch_event_count + clob_archive_event_count
        clob_batch_count = self.connection.execute(
            "SELECT COUNT(*) FROM polymarket_clob_event_batches"
        ).fetchone()[0] + self.connection.execute(
            "SELECT COUNT(*) FROM raw_event_batch_catalog WHERE source='POLYMARKET_CLOB'"
        ).fetchone()[0]
        clob_trade_count = self.connection.execute("SELECT COUNT(*) FROM polymarket_clob_trades").fetchone()[0]
        latest_clob_event = self.connection.execute(
            """SELECT received_timestamp FROM (
                SELECT received_timestamp FROM polymarket_clob_events
                UNION ALL SELECT last_received_timestamp FROM polymarket_clob_event_batches
                UNION ALL SELECT last_received_timestamp FROM raw_event_batch_catalog
                    WHERE source='POLYMARKET_CLOB'
            ) ORDER BY received_timestamp DESC LIMIT 1"""
        ).fetchone()
        latest_orderbook_snapshot = self.connection.execute(
            "SELECT received_timestamp FROM orderbook_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        binance_ws_event_count = self.connection.execute(
            "SELECT COALESCE(SUM(event_count), 0) FROM binance_ws_event_batches"
        ).fetchone()[0] + self.connection.execute(
            """SELECT COALESCE(SUM(event_count), 0) FROM raw_event_batch_catalog
            WHERE source='BINANCE_WS'"""
        ).fetchone()[0]
        binance_ws_batch_count = self.connection.execute(
            "SELECT COUNT(*) FROM binance_ws_event_batches"
        ).fetchone()[0] + self.connection.execute(
            "SELECT COUNT(*) FROM raw_event_batch_catalog WHERE source='BINANCE_WS'"
        ).fetchone()[0]
        binance_ws_trade_count = self.connection.execute(
            "SELECT COALESCE(SUM(trade_count), 0) FROM binance_orderflow_seconds"
        ).fetchone()[0]
        binance_ws_book_count = self.connection.execute(
            "SELECT COUNT(*) FROM binance_ws_book_snapshots"
        ).fetchone()[0]
        latest_binance_ws_event = self.connection.execute(
            """SELECT last_received_timestamp FROM (
                SELECT last_received_timestamp FROM binance_ws_event_batches
                UNION ALL SELECT last_received_timestamp FROM raw_event_batch_catalog
                    WHERE source='BINANCE_WS'
            ) ORDER BY last_received_timestamp DESC LIMIT 1"""
        ).fetchone()
        raw_archive_stats = self.connection.execute(
            """SELECT COUNT(DISTINCT archive_path), COUNT(*),
            COALESCE(SUM(event_count), 0), COALESCE(SUM(compressed_size), 0)
            FROM raw_event_batch_catalog"""
        ).fetchone()
        binance_ws_health_rows = self.connection.execute(
            """SELECT connection_name, last_stream, last_source_timestamp,
            last_received_timestamp FROM binance_ws_stream_health"""
        ).fetchall()
        return {
            "markets": market_count,
            "orderbook_snapshots": book_count,
            "polymarket_relevant_markets": len(relevant_market_rows),
            "polymarket_relevant_markets_with_books": len(complete_relevant_books),
            "polymarket_relevant_book_coverage": (
                len(complete_relevant_books) / len(relevant_market_rows)
                if relevant_market_rows else 0.0
            ),
            **poll_metrics(rolling_book_poll, "30m"),
            **poll_metrics(daily_book_poll, "24h"),
            **poll_metrics(lifetime_book_poll, "audit"),
            "polymarket_book_audit_started_at": lifetime_book_poll[7],
            "polymarket_book_gap_events": int(book_gap_stats[0] or 0),
            "polymarket_open_book_gaps": int(book_gap_stats[1] or 0),
            "polymarket_recovered_book_gaps": int(book_gap_stats[2] or 0),
            "polymarket_relevant_open_book_gaps": int(relevant_open_book_gaps or 0),
            "polymarket_oldest_open_book_gap_at": book_gap_stats[3],
            "latest_polymarket_book_poll_at": rolling_book_poll[6],
            "latest_complete_orderbook_pair_at": latest_complete_book_at,
            "polymarket_relevant_book_missing": [
                {"market_id": row[0], "slug": row[1], "up": row[2] is not None, "down": row[3] is not None}
                for row in relevant_market_rows
                if row[2] is None or row[3] is None
            ][:10],
            "polymarket_clob_events": clob_event_count,
            "polymarket_clob_event_batches": clob_batch_count,
            "polymarket_clob_trades": clob_trade_count,
            "latest_polymarket_clob_event_at": latest_clob_event[0] if latest_clob_event else None,
            "latest_orderbook_snapshot_at": latest_orderbook_snapshot[0] if latest_orderbook_snapshot else None,
            "binance_feature_snapshots": feature_count,
            "latest_binance_feature_source_at": latest_feature[0] if latest_feature else None,
            "latest_binance_feature_at": latest_feature[1] if latest_feature else None,
            "binance_ws_events": binance_ws_event_count,
            "binance_ws_event_batches": binance_ws_batch_count,
            "binance_ws_trades": binance_ws_trade_count,
            "binance_ws_book_snapshots": binance_ws_book_count,
            "latest_binance_ws_event_at": latest_binance_ws_event[0] if latest_binance_ws_event else None,
            "raw_archive_partitions": raw_archive_stats[0],
            "raw_archive_batches": raw_archive_stats[1],
            "raw_archive_events": raw_archive_stats[2],
            "raw_archive_compressed_bytes": raw_archive_stats[3],
            "binance_ws_stream_health": {
                str(row[0]): {
                    "last_stream": row[1], "last_source_timestamp": row[2],
                    "last_received_timestamp": row[3],
                }
                for row in binance_ws_health_rows
            },
            "research_predictions": prediction_count,
            "chainlink_market_labels": label_count,
            "reconciled_market_labels": reconciled_label_count,
            "resolution_reconciliation_mismatches": reconciliation_mismatches,
            "training_ready_markets": training_ready_markets,
            "realtime_training_ready_markets": realtime_training_ready_markets,
            "verified_chainlink_observations": chainlink_observation_count,
            "chainlink_raw_events": chainlink_raw_event_count,
            "latest_chainlink_observation_at": latest_chainlink[0] if latest_chainlink else None,
            "resolution_state_snapshots": int(resolution_state_stats[0] or 0),
            "latest_resolution_state_at": resolution_state_stats[1],
            "resolution_state_incomplete_snapshots": int(resolution_state_stats[2] or 0),
            "fee_rule_versions": fee_rule_count,
            "paper_orders": paper_order_count,
            "paper_realized_pnl": paper_pnl,
            "capacity_points": capacity_count,
            "research_ledger_entries": research_ledger_count,
            "research_ledger_settled": research_ledger_settled,
            "research_ledger_settled_markets": research_ledger_settled_markets,
            "research_ledger_realized_pnl": research_ledger_pnl,
            "latest_run": dict(zip(
                ("started_at", "completed_at", "status", "markets_discovered", "books_saved", "error"), latest
            )) if latest else None,
        }

    def save_binance_features(self, snapshot: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO binance_feature_snapshots(
                symbol, source_timestamp, received_timestamp, spot_bid, spot_ask,
                spot_mid, spot_imbalance, futures_bid, futures_ask, futures_mid,
                futures_imbalance, basis_bps, open_interest, funding_rate,
                mark_price, index_price, raw_json, snapshot_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot["symbol"], snapshot["source_timestamp"], snapshot["received_timestamp"],
                snapshot["spot_bid"], snapshot["spot_ask"], snapshot["spot_mid"],
                snapshot["spot_imbalance"], snapshot["futures_bid"], snapshot["futures_ask"],
                snapshot["futures_mid"], snapshot["futures_imbalance"], snapshot["basis_bps"],
                snapshot["open_interest"], snapshot["funding_rate"], snapshot["mark_price"],
                snapshot["index_price"], json.dumps(snapshot["raw"], sort_keys=True),
                snapshot["snapshot_hash"],
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def current_research_inputs(self, now_iso: str) -> dict | None:
        market = self.connection.execute(
            """SELECT market_id, slug, start_time, end_time, up_token_id, down_token_id,
            rule_hash FROM polymarket_markets
            WHERE start_time <= ? AND end_time > ? ORDER BY start_time DESC LIMIT 1""",
            (now_iso, now_iso),
        ).fetchone()
        if not market:
            return None
        names = ("market_id", "slug", "start_time", "end_time", "up_token_id", "down_token_id", "rule_hash")
        result = dict(zip(names, market))
        books = {}
        for outcome, token in (("UP", result["up_token_id"]), ("DOWN", result["down_token_id"])):
            row = self.connection.execute(
                """SELECT source_timestamp, received_timestamp, bids_json, asks_json
                FROM orderbook_snapshots WHERE token_id=? ORDER BY id DESC LIMIT 1""",
                (token,),
            ).fetchone()
            if row:
                books[outcome] = {
                    "source_timestamp": row[0], "received_timestamp": row[1],
                    "bids": json.loads(row[2]), "asks": json.loads(row[3]),
                }
        result["books"] = books
        feature = self.connection.execute(
            """SELECT source_timestamp, received_timestamp, spot_mid, spot_imbalance,
            futures_mid, futures_imbalance, basis_bps, open_interest, funding_rate,
            mark_price, index_price FROM binance_feature_snapshots ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if feature:
            feature_names = (
                "source_timestamp", "received_timestamp", "spot_mid", "spot_imbalance",
                "futures_mid", "futures_imbalance", "basis_bps", "open_interest",
                "funding_rate", "mark_price", "index_price",
            )
            result["binance"] = dict(zip(feature_names, feature))
        verified_count = self.connection.execute(
            """SELECT COUNT(*) FROM chainlink_observations
            WHERE market_id=? AND verification_status='VERIFIED'""", (result["market_id"],)
        ).fetchone()[0]
        result["verified_chainlink_observations"] = verified_count
        return result

    def live_polymarket_markets(self, now_iso: str, horizon_iso: str, limit: int = 2) -> list[dict]:
        """Return compact current/next market snapshots for status projections.

        The normalized orderbook table remains authoritative for executable top-of-book
        prices.  This deliberately avoids returning full depth through the status API.
        """
        rows = self.connection.execute(
            """SELECT market_id, slug, condition_id, start_time, end_time, rule_hash
            FROM polymarket_markets
            WHERE end_time > ? AND start_time <= ?
            ORDER BY start_time LIMIT ?""",
            (now_iso, horizon_iso, limit),
        ).fetchall()
        names = ("market_id", "slug", "condition_id", "start_time", "end_time", "rule_hash")
        markets: list[dict] = []
        for row in rows:
            market = dict(zip(names, row))
            market["phase"] = "CURRENT" if market["start_time"] <= now_iso < market["end_time"] else "NEXT"
            books: dict[str, dict] = {}
            for outcome in ("UP", "DOWN"):
                book = self.connection.execute(
                    """SELECT source_timestamp, received_timestamp, best_bid, best_ask,
                    microprice, spread FROM orderbook_snapshots
                    WHERE market_id=? AND outcome=? ORDER BY id DESC LIMIT 1""",
                    (market["market_id"], outcome),
                ).fetchone()
                if book:
                    books[outcome] = dict(zip(
                        ("source_timestamp", "received_timestamp", "best_bid", "best_ask", "microprice", "spread"),
                        book,
                    ))
            market["books"] = books
            markets.append(market)
        return markets

    def markets_for_chainlink_timestamp(self, timestamp_iso: str) -> list[dict]:
        """Return every market whose resolution window contains this observation."""
        rows = self.connection.execute(
            """SELECT market_id, start_time, end_time, rule_hash
            FROM polymarket_markets
            WHERE start_time <= ? AND end_time >= ?
            ORDER BY start_time""",
            (timestamp_iso, timestamp_iso),
        ).fetchall()
        return [dict(zip(("market_id", "start_time", "end_time", "rule_hash"), row)) for row in rows]

    def save_research_prediction(self, prediction: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO research_predictions(
                market_id, prediction_timestamp, market_probability_up, p_raw,
                p_calibrated, p_lower, p_upper, conservative_edge, decision,
                no_trade_reasons_json, features_json, feature_schema_version,
                realtime_feature_version, model_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                prediction["market_id"], prediction["prediction_timestamp"],
                prediction.get("market_probability_up"), prediction.get("p_raw"),
                prediction.get("p_calibrated"), prediction.get("p_lower"),
                prediction.get("p_upper"), prediction.get("conservative_edge"),
                prediction["decision"], json.dumps(prediction["no_trade_reasons"], sort_keys=True),
                json.dumps(prediction.get("features", {}), sort_keys=True),
                prediction.get("features", {}).get("feature_schema_version"),
                prediction.get("features", {}).get("realtime_feature_version"),
                prediction["model_version"],
            ),
        )
        if cursor.rowcount > 0 and prediction.get("p_calibrated") is not None:
            features = prediction.get("features", {})
            side = features.get("research_side")
            price = features.get("research_executable_price")
            fees = float(features.get("research_fees_per_share") or 0.0)
            if side in ("UP", "DOWN") and price is not None and float(price) + fees > 0:
                cost_per_share = float(price) + fees
                self.connection.execute(
                    """INSERT OR IGNORE INTO research_ledger(
                        market_id, prediction_timestamp, side, decision,
                        model_probability, market_probability, executable_price,
                        fees_per_share, normalized_stake, normalized_shares,
                        expected_net_edge, conservative_net_edge,
                        no_trade_reasons_json, model_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?, ?, ?)""",
                    (
                        prediction["market_id"], prediction["prediction_timestamp"], side,
                        prediction["decision"], prediction["p_calibrated"],
                        prediction["market_probability_up"], float(price), fees,
                        1.0 / cost_per_share,
                        float(features.get("research_net_edge") or 0.0),
                        float(features.get("research_conservative_net_edge") or 0.0),
                        json.dumps(prediction["no_trade_reasons"], sort_keys=True),
                        prediction["model_version"],
                    ),
                )
        self.connection.commit()
        return cursor.rowcount > 0

    def settle_research_ledger(self) -> int:
        rows = self.connection.execute(
            """SELECT r.id, r.side, r.normalized_stake, r.normalized_shares, l.outcome
            FROM research_ledger r INNER JOIN market_labels l ON l.market_id=r.market_id
            WHERE r.settled_at IS NULL"""
        ).fetchall()
        settled_at = datetime.now(timezone.utc).isoformat()
        for row_id, side, stake, shares, outcome in rows:
            pnl = (float(shares) if side == outcome else 0.0) - float(stake)
            self.connection.execute(
                """UPDATE research_ledger SET outcome=?, realized_pnl=?, settled_at=?
                WHERE id=? AND settled_at IS NULL""",
                (outcome, pnl, settled_at, row_id),
            )
        self.connection.commit()
        return len(rows)

    def latest_research_prediction(self) -> dict | None:
        row = self.connection.execute(
            """SELECT market_id, prediction_timestamp, market_probability_up, p_raw,
            p_calibrated, p_lower, p_upper, conservative_edge, decision,
            no_trade_reasons_json, features_json, model_version
            FROM research_predictions ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        names = (
            "market_id", "prediction_timestamp", "market_probability_up", "p_raw",
            "p_calibrated", "p_lower", "p_upper", "conservative_edge", "decision",
            "no_trade_reasons", "features", "model_version",
        )
        result = dict(zip(names, row))
        result["no_trade_reasons"] = json.loads(result["no_trade_reasons"])
        result["features"] = json.loads(result["features"])
        return result

    def resolution_inputs(self, market_id: str, rule_hash: str) -> dict | None:
        rule_row = self.connection.execute(
            """SELECT payload_json FROM market_rule_versions
            WHERE market_id=? AND resolution_rule_hash=?""", (market_id, rule_hash)
        ).fetchone()
        if not rule_row:
            return None
        observations = self.connection.execute(
            """SELECT stream_id, report_id, source_timestamp, received_timestamp,
            twap_60s, verification_status, raw_payload_hash
            FROM chainlink_observations WHERE market_id=? ORDER BY source_timestamp""",
            (market_id,),
        ).fetchall()
        return {"rule": json.loads(rule_row[0]), "observations": [
            {
                "stream_id": row[0], "report_id": row[1], "source_timestamp": row[2],
                "received_timestamp": row[3], "twap_60s": row[4],
                "verification_status": row[5], "raw_payload_hash": row[6],
            } for row in observations
        ]}

    def recent_spot_mids(self, limit: int = 60, before_iso: str | None = None) -> list[float]:
        if before_iso is None:
            rows = self.connection.execute(
                "SELECT spot_mid FROM binance_feature_snapshots ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.connection.execute(
                """SELECT spot_mid FROM binance_feature_snapshots
                WHERE source_timestamp < ? ORDER BY id DESC LIMIT ?""", (before_iso, limit)
            ).fetchall()
        return [float(row[0]) for row in reversed(rows)]

    def recent_orderbook_microstructure(self, before_iso: str, limit: int = 300) -> list[dict]:
        rows = self.connection.execute(
            """SELECT spread, bids_json, asks_json FROM orderbook_snapshots
            WHERE source_timestamp < ? AND spread IS NOT NULL
            ORDER BY id DESC LIMIT ?""", (before_iso, limit)
        ).fetchall()
        result = []
        for spread, bids_json, asks_json in reversed(rows):
            bids, asks = json.loads(bids_json), json.loads(asks_json)
            depth = sum(float(item["size"]) for item in bids[:5] + asks[:5])
            result.append({"spread": float(spread), "depth": depth})
        return result

    def markets_pending_labels(self, now_iso: str, limit: int = 100) -> list[dict]:
        rows = self.connection.execute(
            """SELECT DISTINCT m.market_id, m.rule_hash FROM polymarket_markets m
            INNER JOIN chainlink_observations c ON c.market_id=m.market_id
            LEFT JOIN market_labels l ON l.market_id=m.market_id
            LEFT JOIN resolution_state_snapshots s
                ON s.market_id=m.market_id AND s.rule_hash=m.rule_hash
                AND s.calculated_at=m.end_time
            WHERE m.end_time <= ? AND (l.market_id IS NULL OR l.label_version != 'endpoint-twap-v2')
            AND (
                s.id IS NULL OR s.observation_count < (
                    SELECT COUNT(*) FROM chainlink_observations cx
                    WHERE cx.market_id=m.market_id AND cx.verification_status='VERIFIED'
                )
            )
            ORDER BY m.end_time DESC LIMIT ?""", (now_iso, limit)
        ).fetchall()
        return [{"market_id": row[0], "rule_hash": row[1]} for row in rows]

    def save_market_label(self, label: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT INTO market_labels(
                market_id, rule_hash, source, start_price, final_twap,
                outcome, observation_count, finalized_at, label_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'endpoint-twap-v2')
            ON CONFLICT(market_id) DO UPDATE SET
                rule_hash=excluded.rule_hash, source=excluded.source,
                start_price=excluded.start_price, final_twap=excluded.final_twap,
                outcome=excluded.outcome, observation_count=excluded.observation_count,
                finalized_at=excluded.finalized_at, label_version=excluded.label_version""",
            (
                label["market_id"], label["rule_hash"], "CHAINLINK_VERIFIED",
                label["start_price"], label["final_twap"], label["outcome"],
                label["observation_count"], label["finalized_at"],
            ),
        )
        self.connection.commit()
        if cursor.rowcount > 0:
            self.connection.execute("DELETE FROM resolution_reconciliations WHERE market_id=?", (label["market_id"],))
            self.connection.commit()
        return cursor.rowcount > 0

    def save_resolution_state(
        self, state, rule_hash: str, calculated_at: str, observation_count: int,
    ) -> bool:
        cursor = self.connection.execute(
            """INSERT INTO resolution_state_snapshots(
                market_id, rule_hash, calculated_at, start_price,
                accumulated_price_time, current_cumulative_twap, remaining_duration,
                required_remaining_twap, required_future_twap_gap, resolution_pressure,
                provisional_resolution, resolution_confidence, fraction_window_observed,
                settlement_complete, data_complete, observation_count, no_trade_reasons_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id, rule_hash, calculated_at) DO UPDATE SET
                start_price=excluded.start_price,
                accumulated_price_time=excluded.accumulated_price_time,
                current_cumulative_twap=excluded.current_cumulative_twap,
                remaining_duration=excluded.remaining_duration,
                required_remaining_twap=excluded.required_remaining_twap,
                required_future_twap_gap=excluded.required_future_twap_gap,
                resolution_pressure=excluded.resolution_pressure,
                provisional_resolution=excluded.provisional_resolution,
                resolution_confidence=excluded.resolution_confidence,
                fraction_window_observed=excluded.fraction_window_observed,
                settlement_complete=excluded.settlement_complete,
                data_complete=excluded.data_complete,
                observation_count=excluded.observation_count,
                no_trade_reasons_json=excluded.no_trade_reasons_json""",
            (
                state.market_id, rule_hash, calculated_at, state.start_price,
                state.accumulated_price_time, state.current_cumulative_twap,
                state.remaining_duration, state.required_remaining_twap,
                state.required_future_twap_gap, state.resolution_pressure,
                state.provisional_resolution.value if state.provisional_resolution else None,
                state.resolution_confidence, state.fraction_window_observed,
                int(state.complete), int(not state.no_trade_reasons), observation_count,
                json.dumps(state.no_trade_reasons, sort_keys=True),
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def reconcile_resolved_markets(self) -> dict[str, int]:
        rows = self.connection.execute(
            """SELECT l.market_id, l.outcome, m.raw_json
            FROM market_labels l
            INNER JOIN polymarket_markets m ON m.market_id=l.market_id
            LEFT JOIN resolution_reconciliations r ON r.market_id=l.market_id
            WHERE m.closed=1 AND r.market_id IS NULL"""
        ).fetchall()
        checked = mismatches = 0
        for market_id, internal_outcome, raw_json in rows:
            raw = json.loads(raw_json)
            outcomes = raw.get("outcomes") or []
            prices = raw.get("outcomePrices") or []
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if isinstance(prices, str):
                prices = json.loads(prices)
            if len(outcomes) != 2 or len(prices) != 2:
                continue
            numeric = [float(value) for value in prices]
            winner_index = max(range(2), key=numeric.__getitem__)
            if numeric[winner_index] < .99:
                continue
            winner = str(outcomes[winner_index]).upper()
            winner = "UP" if winner in ("UP", "YES") else "DOWN" if winner in ("DOWN", "NO") else winner
            matches = winner == internal_outcome
            payload_hash = sha256(raw_json.encode()).hexdigest()
            self.connection.execute(
                """INSERT OR IGNORE INTO resolution_reconciliations(
                    market_id, internal_outcome, polymarket_outcome, matches,
                    checked_at, market_payload_hash
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (market_id, internal_outcome, winner, int(matches), datetime.now(timezone.utc).isoformat(), payload_hash),
            )
            checked += 1
            mismatches += int(not matches)
        self.connection.commit()
        return {"checked": checked, "mismatches": mismatches}

    def alpha_training_rows(self) -> list[dict]:
        rows = self.connection.execute(
            """SELECT p.market_id, p.prediction_timestamp, p.market_probability_up,
            p.features_json, l.outcome, m.start_time, m.end_time
            FROM research_predictions p
            INNER JOIN market_labels l ON l.market_id=p.market_id
            INNER JOIN resolution_reconciliations r ON r.market_id=p.market_id AND r.matches=1
            INNER JOIN polymarket_markets m ON m.market_id=p.market_id
            WHERE p.market_probability_up IS NOT NULL
            AND p.prediction_timestamp < m.end_time
            ORDER BY m.start_time, p.prediction_timestamp"""
        ).fetchall()
        from .training import (
            FEATURE_SCHEMA_VERSION, LEGACY_FEATURE_SCHEMA_VERSIONS,
            REQUIRED_RESOLUTION_FEATURES, upgrade_feature_schema,
        )
        result = []
        for row in rows:
            features = json.loads(row[3])
            if features.get("feature_schema_version") not in (FEATURE_SCHEMA_VERSION, *LEGACY_FEATURE_SCHEMA_VERSIONS):
                continue
            features = upgrade_feature_schema(features)
            if any(features.get(name) is None for name in REQUIRED_RESOLUTION_FEATURES):
                continue
            result.append({
                "market_id": row[0], "prediction_timestamp": row[1],
                "market_probability_up": float(row[2]), "features": features,
                "outcome": 1 if row[4] == "UP" else 0,
                "start_time": row[5], "end_time": row[6],
            })
        return result

    def initialize_paper_accounts(self, starting_cash: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for scenario in ("OPTIMISTIC", "ESTIMATED", "CONSERVATIVE"):
            self.connection.execute(
                "INSERT OR IGNORE INTO paper_accounts VALUES (?, ?, ?, ?)",
                (scenario, starting_cash, starting_cash, now),
            )
        self.connection.commit()

    def next_paper_signal(self) -> dict | None:
        row = self.connection.execute(
            """SELECT p.market_id, p.prediction_timestamp, p.decision,
            p.conservative_edge, p.features_json
            FROM research_predictions p
            WHERE p.decision IN ('MAKER','TAKER')
            AND NOT EXISTS (SELECT 1 FROM paper_orders o WHERE o.market_id=p.market_id)
            ORDER BY p.id LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        return {
            "market_id": row[0], "prediction_timestamp": row[1],
            "kind": row[2], "conservative_edge": row[3], "features": json.loads(row[4]),
        }

    def latest_book_for_outcome(self, market_id: str, outcome: str) -> dict | None:
        row = self.connection.execute(
            """SELECT token_id, source_timestamp, bids_json, asks_json
            FROM orderbook_snapshots WHERE market_id=? AND outcome=?
            ORDER BY id DESC LIMIT 1""", (market_id, outcome)
        ).fetchone()
        if not row:
            return None
        return {"token_id": row[0], "source_timestamp": row[1], "bids": json.loads(row[2]), "asks": json.loads(row[3])}

    def create_paper_order(self, order: dict) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO paper_orders(
                market_id, prediction_timestamp, scenario, kind, side, limit_price,
                requested_shares, estimated, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)""",
            (
                order["market_id"], order["prediction_timestamp"], order["scenario"],
                order["kind"], order["side"], order["limit_price"], order["requested_shares"],
                int(order["scenario"] != "OPTIMISTIC"), now, now,
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def open_paper_orders(self) -> list[dict]:
        rows = self.connection.execute(
            """SELECT o.id, o.market_id, o.scenario, o.kind, o.side, o.limit_price,
            o.requested_shares, m.end_time FROM paper_orders o
            JOIN polymarket_markets m ON m.market_id=o.market_id WHERE o.status='OPEN'"""
        ).fetchall()
        names = ("id", "market_id", "scenario", "kind", "side", "limit_price", "requested_shares", "end_time")
        return [dict(zip(names, row)) for row in rows]

    def fill_paper_order(self, order_id: int, fill_probability: float, filled: float, average_price: float) -> bool:
        scenario = self.connection.execute("SELECT scenario FROM paper_orders WHERE id=?", (order_id,)).fetchone()
        if not scenario:
            return False
        account = self.connection.execute("SELECT cash FROM paper_accounts WHERE scenario=?", (scenario[0],)).fetchone()
        affordable = min(filled, (account[0] / average_price) if account and average_price > 0 else 0.0)
        if affordable <= 0:
            return False
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """UPDATE paper_orders SET fill_probability=?, filled_shares=?, average_price=?,
            status='FILLED', updated_at=? WHERE id=? AND status='OPEN'""",
            (fill_probability, affordable, average_price, now, order_id),
        )
        self.connection.execute(
            "UPDATE paper_accounts SET cash=cash-?, updated_at=? WHERE scenario=?",
            (affordable * average_price, now, scenario[0]),
        )
        self.connection.commit()
        return True

    def cancel_paper_order(self, order_id: int) -> None:
        self.connection.execute(
            "UPDATE paper_orders SET status='CANCELLED', updated_at=? WHERE id=? AND status='OPEN'",
            (datetime.now(timezone.utc).isoformat(), order_id),
        )
        self.connection.commit()

    def settle_paper_orders(self) -> int:
        rows = self.connection.execute(
            """SELECT o.id, o.scenario, o.side, o.filled_shares, o.average_price, l.outcome
            FROM paper_orders o JOIN market_labels l ON l.market_id=o.market_id
            WHERE o.status='FILLED'"""
        ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        for order_id, scenario, side, shares, price, outcome in rows:
            payout = shares if side == outcome else 0.0
            pnl = payout - shares * price
            self.connection.execute(
                "UPDATE paper_orders SET status='SETTLED', realized_pnl=?, updated_at=? WHERE id=?",
                (pnl, now, order_id),
            )
            self.connection.execute(
                "UPDATE paper_accounts SET cash=cash+?, updated_at=? WHERE scenario=?",
                (payout, now, scenario),
            )
        self.connection.commit()
        return len(rows)

    def save_capacity_point(self, point: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO capacity_snapshots(
                market_id, prediction_timestamp, side, capital, executable_fraction,
                average_price, average_slippage, net_edge, capacity_limited, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                point["market_id"], point["prediction_timestamp"], point["side"],
                point["capital"], point["executable_fraction"], point["average_price"],
                point["average_slippage"], point["net_edge"], int(point["capacity_limited"]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def save_chainlink_raw_report(self, report: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO chainlink_raw_reports(
                feed_id, observations_timestamp, valid_from_timestamp,
                received_timestamp, full_report, raw_payload_hash, verification_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                report["feed_id"], report["observations_timestamp"],
                report["valid_from_timestamp"], report["received_timestamp"],
                report["full_report"], report["raw_payload_hash"],
                report.get("verification_status", "UNVERIFIED"),
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def save_chainlink_rtds_event(self, event: dict) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO chainlink_rtds_events(
                raw_payload_hash, topic, symbol, window_seconds, source_timestamp,
                received_timestamp, exact_value, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["raw_payload_hash"], event["topic"], event["symbol"],
                event["window_seconds"], event["source_timestamp"],
                event["received_timestamp"], event["exact_value"],
                json.dumps(event["raw"], sort_keys=True, default=str),
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def save_rule(self, rule: MarketRuleVersion) -> None:
        payload = asdict(rule)
        payload["start_time"] = rule.start_time.isoformat()
        payload["end_time"] = rule.end_time.isoformat()
        self.connection.execute(
            "INSERT OR IGNORE INTO market_rule_versions VALUES (?, ?, ?, ?)",
            (rule.market_id, rule.resolution_rule_hash, json.dumps(payload, sort_keys=True), datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def save_chainlink(self, observation: ChainlinkObservation) -> None:
        self.connection.execute(
            """INSERT OR IGNORE INTO chainlink_observations
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation.market_id,
                observation.stream_id,
                observation.report_id,
                observation.source_timestamp.isoformat(),
                observation.received_timestamp.isoformat(),
                observation.twap_60s,
                observation.verification_status.value,
                observation.raw_payload_hash,
            ),
        )
        self.connection.commit()

    def audit(self, event_type: str, payload: dict) -> None:
        self.connection.execute(
            "INSERT INTO audit_events(timestamp, event_type, payload_json) VALUES (?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), event_type, json.dumps(payload, sort_keys=True)),
        )
        self.connection.commit()

    def latest_model_audit(self) -> dict | None:
        row = self.connection.execute(
            """SELECT timestamp, event_type, payload_json FROM audit_events
            WHERE event_type IN (
                'auto_model_published', 'auto_model_rejected',
                'lightgbm_challenger_evaluated', 'auto_model_subprocess_error',
                'auto_model_training_started'
            ) ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0], "event_type": row[1],
            "payload": json.loads(row[2]),
        }

    def close(self) -> None:
        for connection in self._raw_archive_connections.values():
            connection.close()
        self._raw_archive_connections.clear()
        self.connection.close()
