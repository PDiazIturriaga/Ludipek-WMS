import os
import requests
import pandas as pd
from requests_oauthlib import OAuth1

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def obtener_credenciales_netsuite() -> tuple:
    """Busca las credenciales tanto con prefijo NETSUITE_ (Render) como DB_ (Windows local)."""
    account_id = (
        os.getenv("NETSUITE_ACCOUNT_ID")
        or os.getenv("DB_ACCOUNT_ID")
        or ""
    ).strip()
    consumer_key = (
        os.getenv("NETSUITE_CONSUMER_KEY")
        or os.getenv("DB_CONSUMER_KEY")
        or ""
    ).strip()
    consumer_secret = (
        os.getenv("NETSUITE_CONSUMER_SECRET")
        or os.getenv("DB_CONSUMER_SECRET")
        or ""
    ).strip()
    token_id = (
        os.getenv("NETSUITE_TOKEN_KEY")
        or os.getenv("NETSUITE_TOKEN_ID")
        or os.getenv("DB_TOKEN_ID")
        or os.getenv("DB_TOKEN_KEY")
        or ""
    ).strip()
    token_secret = (
        os.getenv("NETSUITE_TOKEN_SECRET")
        or os.getenv("DB_TOKEN_SECRET")
        or ""
    ).strip()
    return account_id, consumer_key, consumer_secret, token_id, token_secret


def consultar_netsuite(query_sql: str, max_registros: int = 5000):
    """
    Se conecta a la API REST SuiteQL de NetSuite siendo 100% compatible
    con Render (NETSUITE_*) y con Windows local (DB_*).
    """
    account_id, consumer_key, consumer_secret, token_id, token_secret = obtener_credenciales_netsuite()

    if not all([account_id, consumer_key, consumer_secret, token_id, token_secret]):
        faltantes = []
        if not account_id:
            faltantes.append("NETSUITE_ACCOUNT_ID")
        if not consumer_key:
            faltantes.append("NETSUITE_CONSUMER_KEY")
        if not consumer_secret:
            faltantes.append("NETSUITE_CONSUMER_SECRET")
        if not token_id:
            faltantes.append("NETSUITE_TOKEN_KEY")
        if not token_secret:
            faltantes.append("NETSUITE_TOKEN_SECRET")
        print(f"[ERROR NETSUITE] Faltan variables de entorno: {', '.join(faltantes)}")
        return None

    # URL requiere minúsculas con guion; Realm OAuth requiere mayúsculas con guion bajo
    account_url = str(account_id).lower().replace("_", "-")
    account_realm = str(account_id).upper().replace("-", "_")
    url_base = f"https://{account_url}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"

    auth = OAuth1(
        client_key=consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=token_id,
        resource_owner_secret=token_secret,
        realm=account_realm,
        signature_method="HMAC-SHA256",
    )

    headers = {
        "Prefer": "transient",
        "Content-Type": "application/json",
    }

    todos_los_registros = []
    limite = 1000
    offset = 0
    hay_mas_datos = True

    while hay_mas_datos:
        url_paginada = f"{url_base}?limit={limite}&offset={offset}"
        try:
            response = requests.post(
                url_paginada,
                auth=auth,
                headers=headers,
                json={"q": query_sql},
                timeout=25,
            )

            if response.status_code == 200:
                datos = response.json()
                items = datos.get("items", [])
                todos_los_registros.extend(items)

                if datos.get("hasMore") is True and len(todos_los_registros) < max_registros:
                    offset += limite
                else:
                    hay_mas_datos = False
            else:
                print(f"[ERROR NETSUITE {response.status_code}]: {response.text}")
                return pd.DataFrame(todos_los_registros) if todos_los_registros else None

        except Exception as e:
            print(f"[ERROR CONEXION HTTP NETSUITE]: {e}")
            return pd.DataFrame(todos_los_registros) if todos_los_registros else None

    return pd.DataFrame(todos_los_registros)