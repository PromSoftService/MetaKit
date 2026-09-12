PYTHON ?= python3
DOCS_OUTPUT ?= dist/docs
BASE_URL ?= /docs/

.PHONY: install check docs verify clean

install:
	$(PYTHON) -m pip install -r requirements-docs.txt

check:
	$(PYTHON) tools/validate_metakit.py

docs: check
	$(PYTHON) tools/build_docs.py --output $(DOCS_OUTPUT) --base-url $(BASE_URL)

verify: docs
	$(PYTHON) tools/check_docs.py $(DOCS_OUTPUT) --base-url $(BASE_URL)

clean:
	$(PYTHON) -c "from pathlib import Path; import shutil; shutil.rmtree(Path('dist'), ignore_errors=True)"
