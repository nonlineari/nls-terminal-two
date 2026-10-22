"""Command line for ingest, features, training, and budget splits."""

from __future__ import annotations

import click

from src.config import configure_logging


@click.group()
def cli() -> None:
    """Terminal Two: local promo-budget research for seven Asian markets."""
    configure_logging()


@cli.command("ingest")
def ingest_cmd() -> None:
    """Pull public sources into data/raw and log anything that does not yield numbers."""
    from src.ingestion.run import main as ingest_main

    raise SystemExit(ingest_main())


@cli.command("features")
def features_cmd() -> None:
    """Build data/processed/feature_matrix.csv from the latest raw manifest."""
    from src.features.build import main as build_main

    raise SystemExit(build_main())


@cli.command("train")
def train_cmd() -> None:
    """Fit the XGBoost ensemble and write models/."""
    from src.model.train import main as train_main

    raise SystemExit(train_main())


@cli.command("report")
def report_cmd() -> None:
    """Print LOOCV metrics, the mean baseline, and feature importances."""
    from src.output.recommend import run_report

    raise SystemExit(run_report())


@cli.command("recommend")
@click.option("--budget", type=float, required=True, help="Amount to split. Not converted between currencies.")
def recommend_cmd(budget: float) -> None:
    """Load the model and print a market × channel budget split."""
    if budget <= 0:
        raise click.BadParameter("budget must be positive")
    from src.output.recommend import run_recommend

    raise SystemExit(run_recommend(budget))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
