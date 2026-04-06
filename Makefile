.PHONY: lint typecheck test check

MYPY_FILES = ioe_types.py ioe_crypto.py ioe_telemetry.py webui/auth.py \
	webui/transport.py webui/handler.py client/client.py client/kit_runner.py \
	client/claude_proxy.py add_user.py server/server.py server/browser_handler.py \
	server/claude_chat.py server/telegram_adapter.py client/ioe_web.py \
	webui/html_templates.py webui/css.py

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy $(MYPY_FILES) --ignore-missing-imports --explicit-package-bases --strict

test:
	python -m pytest

check: lint typecheck test
