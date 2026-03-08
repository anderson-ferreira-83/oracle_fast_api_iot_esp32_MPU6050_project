"""
shared/db_oracle.py
Conexao Oracle unificada: ADB Cloud (wallet mTLS) ou XE local.

Uso nos notebooks:
    from shared.db_oracle import get_engine, oracle_connect, DB_MODE

    engine = get_engine()                     # SQLAlchemy engine
    conn   = oracle_connect()                 # oracledb connection direta
"""
from __future__ import annotations

import os
from pathlib import Path

import oracledb

# ---------------------------------------------------------------------------
# Carrega .env.oracle do raiz do projeto
# ---------------------------------------------------------------------------
def _load_env(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


# Tenta .env.oracle relativo ao notebook (notebooks/) e ao raiz do projeto
for _candidate in [
    Path("..") / ".env.oracle",
    Path(".") / ".env.oracle",
    Path(__file__).parents[2] / ".env.oracle",
]:
    if _candidate.exists():
        _load_env(str(_candidate))
        break

# ---------------------------------------------------------------------------
# Parametros lidos do ambiente
# ---------------------------------------------------------------------------
ORACLE_USER            = os.environ.get("ORACLE_USER",            "dersao")
ORACLE_PASSWORD        = os.environ.get("ORACLE_PASSWORD",        "986960440")
ORACLE_DSN             = os.environ.get("ORACLE_DSN",             "")
ORACLE_HOST            = os.environ.get("ORACLE_HOST",            "localhost")
ORACLE_PORT            = os.environ.get("ORACLE_PORT",            "1521")
ORACLE_SERVICE         = os.environ.get("ORACLE_SERVICE_NAME",    "xepdb1")
ORACLE_WALLET_DIR      = os.environ.get("ORACLE_WALLET_DIR",      "")
ORACLE_WALLET_PASSWORD = os.environ.get("ORACLE_WALLET_PASSWORD", "")

# Modo: 'cloud' ou 'local'
DB_MODE     = "cloud" if (ORACLE_DSN and ORACLE_WALLET_DIR) else "local"
DB_MODE_STR = (
    f"ADB Cloud  DSN={ORACLE_DSN}"
    if DB_MODE == "cloud"
    else f"Local  {ORACLE_HOST}:{ORACLE_PORT}/{ORACLE_SERVICE}"
)
# DSN usado para oracledb direto (backward compat com notebooks existentes)
ORACLE_DSN_STR = ORACLE_DSN if DB_MODE == "cloud" else f"{ORACLE_HOST}:{ORACLE_PORT}/{ORACLE_SERVICE}"

# ---------------------------------------------------------------------------
# Constantes de tabela — use em todos os notebooks (evita strings hardcoded)
# ---------------------------------------------------------------------------
TABLE_TRAINING   = "sensor_training_data"   # coletas supervisionadas (treino/CV)
TABLE_MONITORING = "sensor_monitoring_data"  # monitoramento em tempo real (inferencia)
TABLE_LEGACY     = "sensor_data"             # tabela legada (Oracle XE antigo)


# ---------------------------------------------------------------------------
# Conexao direta oracledb (substitui oracledb.connect() nos notebooks)
# ---------------------------------------------------------------------------
def oracle_connect(**extra) -> oracledb.Connection:
    """Retorna uma oracledb.Connection (ADB ou XE local, automatico)."""
    if DB_MODE == "cloud":
        return oracledb.connect(
            user=ORACLE_USER,
            password=ORACLE_PASSWORD,
            dsn=ORACLE_DSN,
            config_dir=ORACLE_WALLET_DIR,
            wallet_location=ORACLE_WALLET_DIR,
            wallet_password=ORACLE_WALLET_PASSWORD,
            **extra,
        )
    return oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN_STR,
        **extra,
    )


# ---------------------------------------------------------------------------
# SQLAlchemy engine (usa creator para evitar re-parsing da senha com @)
# ---------------------------------------------------------------------------
def get_engine(**kwargs):
    """Retorna um SQLAlchemy engine pronto para uso com pandas/read_sql."""
    try:
        from sqlalchemy import create_engine
    except ImportError:
        raise ImportError("pip install sqlalchemy")

    def _creator():
        return oracle_connect()

    return create_engine("oracle+oracledb://", creator=_creator, **kwargs)
