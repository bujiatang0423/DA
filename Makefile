.PHONY: test contract web compileall generated-diff generate-api lint test-postgres verify
test:
	python -m pytest
contract:
	python -m tools.check_openapi
compileall:
	python -m compileall -q backend tools
generated-diff:
	python -m tools.check_openapi
generate-api:
	python -m tools.export_openapi
lint:
	python -m ruff check backend tools
	python -m ruff format --check backend tools
	python -m mypy backend
test-postgres:
	TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+psycopg://da:da@127.0.0.1:55433/da_test} python -m pytest -m postgres
web:
	cd web && npm ci && npm run typecheck && npm test -- --run && npm run build
verify: compileall lint test test-postgres generate-api generated-diff web
