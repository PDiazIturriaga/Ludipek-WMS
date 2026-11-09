import os
import requests
import pandas as pd
from requests_oauthlib import OAuth1

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ULTIMO_ERROR_NETSUITE = ""


def _limpiar_env( *nombres ) -> str:
    for n in nombres:
        val = os.getenv(n)
        if val is not None and str(val).strip() != "":
            return str(val).strip().strip('"').strip("'")
    return ""


def obtener_credenciales_netsuite() -> tuple:
    account_id = _limpiar_env("NETSUITE_ACCOUNT_ID", "DB_ACCOUNT_ID", "ACCOUNT_ID")
    consumer_key = _limpiar_env("NETSUITE_CONSUMER_KEY", "DB_CONSUMER_KEY", "CONSUMER_KEY")
    consumer_secret = _limpiar_env("NETSUITE_CONSUMER_SECRET", "DB_CONSUMER_SECRET", "CONSUMER_SECRET")
    token_id = _limpiar_env("NETSUITE_TOKEN_ID", "NETSUITE_TOKEN_KEY", "DB_TOKEN_ID", "DB_TOKEN_KEY", "TOKEN_ID", "TOKEN_KEY")
    token_secret = _limpiar_env("NETSUITE_TOKEN_SECRET", "DB_TOKEN_SECRET", "TOKEN_SECRET")
    return account_id, consumer_key, consumer_secret, token_id, token_secret


def obtener_ultimo_error_netsuite() -> str:
    return ULTIMO_ERROR_NETSUITE


def consultar_netsuite(query_sql: str, max_registros: int = 2000):
    global ULTIMO_ERROR_NETSUITE
    ULTIMO_ERROR_NETSUITE = ""

    account_id, consumer_key, consumer_secret, token_id, token_secret = obtener_credenciales_netsuite()

    faltantes = []
    if not account_id:
        faltantes.append("ACCOUNT_ID")
    if not consumer_key:
        faltantes.append("CONSUMER_KEY")
    if not consumer_secret:
        faltantes.append("CONSUMER_SECRET")
    if not token_id:
        faltantes.append("TOKEN_ID/KEY")
    if not token_secret:
        faltantes.append("TOKEN_SECRET")

    if faltantes:
        ULTIMO_ERROR_NETSUITE = f"Faltan variables en Render Environment: {', '.join(faltantes)}"
        print(f"[ERROR NETSUITE] {ULTIMO_ERROR_NETSUITE}")
        return None

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
                detalle_http = response.text[:180].replace("\n", " ")
                ULTIMO_ERROR_NETSUITE = f"HTTP {response.status_code}: {detalle_http}"
                print(f"[ERROR NETSUITE] {ULTIMO_ERROR_NETSUITE}")
                return pd.DataFrame(todos_los_registros) if todos_los_registros else None

        except Exception as e:
            ULTIMO_ERROR_NETSUITE = f"Error de red/conexión: {e}"
            print(f"[ERROR CONEXION HTTP NETSUITE]: {e}")
            return pd.DataFrame(todos_los_registros) if todos_los_registros else None

    return pd.DataFrame(todos_los_registros)