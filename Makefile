# Pipeline completo: make data corrupt etl evaluate report test
# Perfil pequeno (sem MySQL, usado no CI): make e2e
SHELL := /bin/bash
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
-include .env
export

.PHONY: env install data generate mysql load extract profile corrupt etl evaluate report test lint e2e clean

env:            ## cria .env com senha aleatória (uma vez)
	@test -f .env || (sed "s/^MYSQL_PASSWORD=.*/MYSQL_PASSWORD=$$($(PY) -c 'import secrets;print(secrets.token_urlsafe(18))')/" .env.example > .env && echo "criado .env")

install:
	$(PY) -m pip install -e ".[dev]"

generate:       ## roda o gerador da fonte (saída em data/generated; a fonte não é alterada)
	$(PY) -m dq.extract.extract generate

mysql: env      ## sobe o MySQL com o schema da fonte
	docker compose up -d --wait mysql

load: mysql     ## carrega os CSV das tabelas do escopo
	docker compose --profile carga run --rm carga

extract:        ## lê o MySQL (ou Parquet no CI) e grava o snapshot de referência
	$(PY) -m dq.extract.extract

profile:        ## perfil de dados da base de referência
	$(PY) -m dq.profile.profiler

ifeq ($(DQ_EXTRACT_BACKEND),parquet)
data: generate extract profile
else
data: env generate load extract profile
endif

corrupt:        ## copia a base e injeta defeitos com registro
	$(PY) -m dq.corrupt.injector

etl:            ## raw -> staging -> clean -> marts (incremental, com quarentena)
	$(PY) -m dq.pipeline etl

evaluate:       ## precisão/recall contra o registro e impacto no negócio
	$(PY) -m dq.pipeline evaluate

report:         ## relatório de qualidade e dashboard estático
	$(PY) -m dq.pipeline report

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests

e2e:            ## ponta a ponta com perfil pequeno, sem MySQL
	$(MAKE) DQ_PROFILE=ci DQ_EXTRACT_BACKEND=parquet DQ_DATA_DIR=data/ci DQ_REPORTS_DIR=data/ci/reports data corrupt etl evaluate report

clean:
	rm -rf data/source data/raw data/raw_reference data/defect_log data/runs
