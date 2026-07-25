# This file expects an .env file to exist that defines MANAGE_PY_PATH
# For example MANAGE_PY_PATH=/home/allianceserver/venv/myauth/manage.py

-include .env
export

appname = aa-killtracker
package = killtracker

help:
	@echo "Makefile for $(appname)"

makemessages:
	cd $(package) && \
	django-admin makemessages \
		-l de \
		-l en \
		-l es \
		-l fr_FR \
		-l it_IT \
		-l ja \
		-l ko_KR \
		-l ru \
		-l uk \
		-l zh_Hans \
		--keep-pot \
		--ignore 'build/*'

tx_push:
	tx push --source

tx_pull:
	tx pull -f

compilemessages:
	cd $(package) && \
	django-admin compilemessages \
		-l de \
		-l en \
		-l es \
		-l fr_FR \
		-l it_IT \
		-l ja \
		-l ko_KR \
		-l ru \
		-l uk \
		-l zh_Hans

coverage:
	coverage run $(MANAGE_PY_PATH) test $(package) --keepdb --failfast && coverage html && coverage report -m

pylint:
	pylint --load-plugins pylint_django $(package)

graph_models:
	python $(MANAGE_PY_PATH) graph_models $(package) --arrow-shape normal -o $(appname)_models.png
