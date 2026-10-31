"""Run the whole pipeline locally without Airflow: extract -> dbt build -> export."""
import subprocess
import sys

import quality
from export import export
from extract import append_snapshot, extract


def main() -> None:
    print("1/3 extract");  append_snapshot(extract())
    if quality.gate():
        return 1
    print("2/3 dbt build")
    subprocess.run(["dbt", "build", "--profiles-dir", "."], check=True)
    print("3/3 export");   export()
    print("done -> docs/data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
