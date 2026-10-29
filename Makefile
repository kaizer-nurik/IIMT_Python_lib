PYTHON ?= python
MANYLINUX ?= manylinux_2_39_x86_64

.PHONY: wheel test notebook benchmark
wheel:
	$(PYTHON) scripts/build_wheels.py --platform $(MANYLINUX)
test:
	$(PYTHON) -m pytest tests -q --junitxml=results/tests.xml
	$(PYTHON) scripts/wheel_smoke.py --junit results/tests.xml
notebook:
	$(PYTHON) -m jupyterlab notebooks/csv_single_dual.ipynb
benchmark:
	$(PYTHON) scripts/benchmark.py
