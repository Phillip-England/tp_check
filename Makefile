PYTHON_APP=tp_check.app:create_app

.PHONY: run test sync

sync:
	uv sync

run:
	uv run flask --app $(PYTHON_APP) run --host 127.0.0.1 --port 8080

test:
	uv run pytest
