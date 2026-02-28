.PHONY: setup lint security test clean help init

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup:  ## Run setup script
	chmod +x setup.sh && ./setup.sh

lint:  ## Run linters
	flake8 *.py --max-line-length=120 --ignore=E501,W503

security:  ## Run security checks
	bandit -r . -x ./venv --severity-level medium
	@echo "Checking for hardcoded secrets..."
	@! grep -rn "password\|secret\|token\|api_key" *.py *.json 2>/dev/null | grep -v "template\|example\|placeholder\|load_secret\|mask_credential\|REDACTED\|\.template\." || echo "No secrets found."

clean:  ## Remove generated files
	rm -rf __pycache__ *.pyc venv/ logs/ data/screenshots/

init:  ## Run setup wizard
	python3 main.py init
