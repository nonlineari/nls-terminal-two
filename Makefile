PYTHON ?= python3

.PHONY: pipeline test recommend ingest features train

pipeline:
	bash scripts/run_pipeline.sh

ingest:
	$(PYTHON) -m src.ingestion.run

features:
	$(PYTHON) -m src.features.build

train:
	$(PYTHON) -m src.model.train

recommend:
	$(PYTHON) -m src.cli recommend --budget 100000

test:
	$(PYTHON) -m unittest discover -s tests -v
