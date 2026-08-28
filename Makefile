.PHONY: build run clean

.venv:
	python3 -m venv .venv
	.venv/bin/pip install -q \
		pyobjc-framework-Cocoa \
		pyobjc-framework-Quartz \
		py2app

build: .venv
	.venv/bin/python setup.py py2app

run: build
	open dist/Ducky.app

clean:
	rm -rf build dist .venv

.DEFAULT_GOAL := run
