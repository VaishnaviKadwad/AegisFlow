import sqlite3
from typing import List
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

app = FastAPI(title="Cloud Ingestion Ledger")

SERVER_DB = "cloud_ledger.db"

def init_server_db():
    conn = sqlite3.connect(SERVER_DB)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            event_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            amount REAL NOT NULL,
            local_timestamp REAL NOT NULL,
            server_received_at REAL DEFAULT (strftime('%s', 'now'))
        )
    """)
    conn.commit()
    conn.close()

init_server_db()

class TransactionPayload(BaseModel):
    event_id: str
    account_id: str
    amount: float
    local_timestamp: float

@app.get("/health")
def health_check():
    return {"status": "ONLINE"}

@app.post("/sync/batch", status_code=status.HTTP_200_OK)
def sync_batch(records: List[TransactionPayload]):
    conn = sqlite3.connect(SERVER_DB)
    cursor = conn.cursor()
    inserted_count = 0
    duplicate_count = 0

    try:
        for r in records:
            try:
                cursor.execute("""
                    INSERT INTO transactions (event_id, account_id, amount, local_timestamp)
                    VALUES (?, ?, ?, ?)
                """, (r.event_id, r.account_id, r.amount, r.local_timestamp))
                inserted_count += 1
            except sqlite3.IntegrityError:
                # Deduplication logic: record already exists, acknowledge safely
                duplicate_count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return {
        "status": "PROCESSED",
        "inserted": inserted_count,
        "duplicates_skipped": duplicate_count
    }

@app.get("/metrics")
def get_metrics():
    conn = sqlite3.connect(SERVER_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions")
    count = cursor.fetchone()[0]
    conn.close()
    return {"total_persisted_records": count}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)