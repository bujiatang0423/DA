.PHONY: test contract web compileall generated-diff verify
test:
	python -m pytest
contract:
	python -m tools.check_openapi
compileall:
	python -m compileall -q backend tools
generated-diff:
	python -m tools.check_openapi
web:
	cd web && npm ci && npm run typecheck && npm test -- --run && npm run build
verify: compileall test contract generated-diff web
