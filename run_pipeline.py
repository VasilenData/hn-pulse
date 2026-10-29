"""Run the whole pipeline locally without Airflow: extract -> dbt build -> export."""
import subprocess
import sys

from export import export
from extract import append_snapshot, extract


def main() -> None:
    print("1/3 extract");  append_snapshot(extract())
    print("2/3 dbt build")
    subprocess.run(["dbt", "build", "--profiles-dir", "."], check=True)
    print("3/3 export");   export()
    print("done -> docs/data.json")


if __name__ == "__main__":
    sys.exit(main())
