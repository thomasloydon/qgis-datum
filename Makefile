PLUGIN   := datum

# QGIS profile plugin folder (macOS default; override on Linux/Windows)
QGIS_PLUGINS ?= $(HOME)/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins

# QGIS's bundled Python, for the headless integration test (macOS app bundle)
QGIS_APP ?= /Applications/QGIS.app/Contents
QGIS_PY  = PYTHONHOME="$(QGIS_APP)/Frameworks" \
           PYTHONPATH="$(QGIS_APP)/Frameworks/lib/python3.12/site-packages:$(QGIS_APP)/Resources/python" \
           QT_QPA_PLATFORM=offscreen PROJ_DATA="$(QGIS_APP)/Resources/qgis/proj" \
           "$(QGIS_APP)/MacOS/python3.12"

.PHONY: lint test test-smoke test-qgis check deploy undeploy zip clean

lint:            ## ruff (pip install ruff)
	ruff check .

test:            ## fast unit tests, no QGIS needed
	python3 -m unittest discover -s tests -v

check:           ## validate metadata.txt (what CI and releases run)
	python3 scripts/release.py check

# QGIS writes one native macOS preference before any redirect can apply; remove it
# afterwards unless it already existed.
QGIS_PLIST := $(HOME)/Library/Preferences/org.qgis.qgis3.QGIS.plist

test-smoke:      ## offline checks inside headless QGIS (what CI runs)
	@had=$$(test -e "$(QGIS_PLIST)" && echo yes); \
	$(QGIS_PY) tests/qgis_smoke.py; rc=$$?; \
	if [ -z "$$had" ]; then defaults delete org.qgis.qgis3.QGIS 2>/dev/null; rm -f "$(QGIS_PLIST)"; fi; \
	exit $$rc

test-qgis:       ## end-to-end inside headless QGIS (uses the network; sandboxed settings)
	@had=$$(test -e "$(QGIS_PLIST)" && echo yes); \
	$(QGIS_PY) tests/qgis_integration.py; rc=$$?; \
	if [ -z "$$had" ]; then defaults delete org.qgis.qgis3.QGIS 2>/dev/null; rm -f "$(QGIS_PLIST)"; fi; \
	exit $$rc

deploy:          ## symlink into your QGIS profile for development
	mkdir -p "$(QGIS_PLUGINS)"
	ln -sfn "$(CURDIR)/$(PLUGIN)" "$(QGIS_PLUGINS)/$(PLUGIN)"
	@echo "Linked. Restart QGIS (or use Plugin Reloader) and enable Datum in Plugins > Manage."

undeploy:
	rm -f "$(QGIS_PLUGINS)/$(PLUGIN)"

zip:             ## build an installable zip (Plugins > Install from ZIP)
	python3 scripts/release.py zip --out dist

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf dist
