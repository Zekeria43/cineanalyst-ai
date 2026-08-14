import os
import clickhouse_connect
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    client = clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST"),
        port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD"),
        database=os.getenv("CLICKHOUSE_DATABASE", "default"),
        secure=True,
    )

    result = client.query("SELECT 1").result_set[0][0]

    print("ClickHouse connection successful!")
    print("Result:", result)