.PHONY: test contract web verify
test:
	python -m pytest
contract:
	python -m tools.check_openapi
web:
	cd web && npm run typecheck && npm test -- --run && npm run build
verify: test contract web
