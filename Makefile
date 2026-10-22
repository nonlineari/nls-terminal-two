.PHONY: pipeline test recommend ingest features train

pipeline:
	bash scripts/run_pipeline.sh

ingest:
	python -m src.ingestion.run

features:
	python -m src.features.build

train:
	python -m src.model.train

recommend:
	python -m src.cli recommend --budget 100000

test:
	python -m unittest discover -s tests -v
