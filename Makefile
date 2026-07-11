.PHONY: test smoke validate verify clean

test:
	python -m pytest -q

smoke:
	PYTHONPATH=src python tools/smoke.py

validate:
	python tools/validate_release.py --write-evidence

verify: test smoke validate

clean:
	rm -rf .pytest_cache build dist release_evidence src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
