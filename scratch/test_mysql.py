import duckdb
from app import config, views

print("MYSQL_URI:", config.MYSQL_URI)
conn = duckdb.connect(":memory:")
conn.execute("INSTALL mysql; LOAD mysql;")
import urllib.parse
parsed = urllib.parse.urlparse(config.MYSQL_URI)
user = parsed.username or "root"
password = parsed.password or ""
host = parsed.hostname or "localhost"
port = parsed.port or 3306
dbname = parsed.path.lstrip("/") or "mysql"

conn_str = f"host={host} port={port} user={user} password={password} database={dbname}"
print("Connecting with:", conn_str)
conn.execute(f"ATTACH '{conn_str}' AS mysql_db (TYPE MYSQL)")
print("Tables in mysql_db:", conn.execute("SHOW TABLES FROM mysql_db").fetchall())

views.build(
    conn,
    overrides={
        "transaction": {"table": "mysql_db.transaction"},
        "account": {"table": "mysql_db.account"},
        "bank": {"table": "mysql_db.bank"},
    },
    as_view=True,
)

print("Views built successfully!")
print("Transaction base count:", conn.execute("SELECT count(*) FROM transaction_base").fetchall())
print("Account base count:", conn.execute("SELECT count(*) FROM account_base").fetchall())
