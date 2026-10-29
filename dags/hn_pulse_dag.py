"""Airflow DAG: extract HN top stories -> dbt build (models + tests) -> export dashboard JSON."""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT = "/opt/airflow/project"

with DAG(
    dag_id="hn_pulse",
    description="Hourly Hacker News front-page snapshot, modelled with dbt",
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    tags=["portfolio", "dbt"],
) as dag:
    extract = BashOperator(task_id="extract", bash_command=f"cd {PROJECT} && python extract.py")
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"cd {PROJECT} && dbt build --profiles-dir .",
    )
    export = BashOperator(task_id="export_dashboard_json", bash_command=f"cd {PROJECT} && python export.py")

    extract >> dbt_build >> export
