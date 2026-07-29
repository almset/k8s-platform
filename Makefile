.PHONY: install-deps validate lint plan install cleanup

install-deps:
	@python3 -m pip install -r scripts/requirements.txt
	@ansible-galaxy collection install -r requirements.yml

validate:
	@python3 scripts/validate.py

lint: validate
	@ansible-playbook site.yml --syntax-check -e platform_action=plan
	@command -v ansible-lint >/dev/null 2>&1 && ansible-lint || echo "ansible-lint not installed, skipping"

plan: validate
	ansible-playbook site.yml -e platform_action=plan

install: validate
	ansible-playbook site.yml -e platform_action=install -e platform_confirm=true

cleanup: validate
	ansible-playbook site.yml -e platform_action=cleanup -e platform_confirm=true
