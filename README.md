# anvil

Asistente on-prem de documentación técnica. Todo corre dentro de la planta.

## Levantar

```bash
docker-compose up -d                     # Postgres 18 + pgvector
.venv/bin/python -m uvicorn anvil.api.main:app --host 0.0.0.0 --port 8080
```

## Accesos

| Qué | URL |
|---|---|
| Portal de consulta (móvil) | `http://<IP-del-servidor>:8080/` |
| **Panel de carga** | `http://<IP-del-servidor>:8080/admin` |
| API docs | `http://<IP-del-servidor>:8080/api/docs` |

## Estado

- ✅ M0 — Postgres 18.6 + pgvector 0.8.6, config de texto `english`/`spanish`/`arabic`
- ✅ M1 — parser docling con página garantizada + chunker estructural (9/9 tests)
- ✅ Portal + panel de carga, ingesta en background
- ✅ M2 — retrieval híbrido (denso + léxico con RRF)
- ✅ M3 — generación con citas vía Qwen local
- ✅ M4 — verificador determinista de datos (19/19 tests)

## Atribución

Ver `CONTEXTO-ANVIL.md` §7.1: se evaluó y midió `microsoft/markitdown` (MIT) antes de
elegir `docling`. Ningún código de markitdown está incorporado en este repo.
