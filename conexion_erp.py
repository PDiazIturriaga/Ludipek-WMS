import requests
import os
import pandas as pd
from requests_oauthlib import OAuth1

# Leer credenciales de NetSuite desde las variables de entorno de Render
CONSUMER_KEY = os.getenv("NETSUITE_CONSUMER_KEY", "").strip()
CONSUMER_SECRET = os.getenv("NETSUITE_CONSUMER_SECRET", "").strip()
TOKEN_KEY = os.getenv("NETSUITE_TOKEN_KEY", "").strip()
TOKEN_SECRET = os.getenv("NETSUITE_TOKEN_SECRET", "").strip()
ACCOUNT_ID = os.getenv("NETSUITE_ACCOUNT_ID", "").strip()

def consultar_netsuite(query_sql):
    """
    Se conecta a la API REST de NetSuite leyendo las credenciales 
    nativas de Windows configuradas por CMD. Incorpora paginación automática
    para superar el límite de 1.000 registros por consulta.
    """
    # Python lee directo del sistema operativo
    account_id = os.getenv('DB_ACCOUNT_ID')
    consumer_key = os.getenv('DB_CONSUMER_KEY')
    consumer_secret = os.getenv('DB_CONSUMER_SECRET')
    token_id = os.getenv('DB_TOKEN_ID')
    token_secret = os.getenv('DB_TOKEN_SECRET')

    # Validación rápida por si falta alguna variable
    if not all([account_id, consumer_key, consumer_secret, token_id, token_secret]):
        print("Error: No se encontraron las variables de entorno. ¿Reiniciaste el editor de código?")
        return None

    # Preparar URL Base y Autenticación
    account_url = str(account_id).lower().replace('_', '-')
    url_base = f"https://{account_url}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"

    auth = OAuth1(
        client_key=consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=token_id,
        resource_owner_secret=token_secret,
        realm=str(account_id),
        signature_method='HMAC-SHA256'
    )

    headers = {
        "Prefer": "transient",
        "Content-Type": "application/json"
    }

    # --- LÓGICA DE PAGINACIÓN ---
    todos_los_registros = []
    limite = 1000
    offset = 0
    hay_mas_datos = True

    while hay_mas_datos:
        # Añadimos los parámetros de paginación a la URL en cada iteración
        url_paginada = f"{url_base}?limit={limite}&offset={offset}"
        
        try:
            response = requests.post(url_paginada, auth=auth, headers=headers, json={"q": query_sql})
            
            if response.status_code == 200:
                datos = response.json()
                items = datos.get('items', [])
                todos_los_registros.extend(items)
                
                # Revisar si NetSuite indica que quedan más páginas
                if datos.get('hasMore') is True:
                    offset += limite
                    print(f"   ↳ Descargando bloque... (van {len(todos_los_registros)} filas)")
                else:
                    hay_mas_datos = False # Rompe el ciclo
            else:
                print(f"Error del servidor ({response.status_code}):\n{response.text}")
                # Si falla en medio de la descarga, devolvemos lo que alcanzó a bajar (o None)
                return pd.DataFrame(todos_los_registros) if todos_los_registros else None
                
        except Exception as e:
            print(f"Error en la conexión HTTP: {e}")
            return pd.DataFrame(todos_los_registros) if todos_los_registros else None

    return pd.DataFrame(todos_los_registros)

# --- BLOQUE DE PRUEBA ---
if __name__ == "__main__":
    # Query sin TOP 5 para probar la paginación real
    query_prueba = """
        SELECT 
            transaction.id AS transaccion_id,
            transaction.trandate AS fecha,
            transaction.type AS tipo
        FROM 
            transaction
    """
    
    print("Conectando con el ERP usando variables nativas de Windows...")
    df_resultado = consultar_netsuite(query_prueba)
    
    if df_resultado is not None and not df_resultado.empty:
        print(f"\n¡Conexión exitosa! Se descargaron en total {len(df_resultado)} registros.")
        print(df_resultado.head())