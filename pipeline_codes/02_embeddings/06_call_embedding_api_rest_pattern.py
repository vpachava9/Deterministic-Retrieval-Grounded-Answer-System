import requests
import json

api_key = dbutils.secrets.get("genai-scope", "embedding_api_key")
api_url = dbutils.secrets.get("genai-scope", "embedding_api_base_url")
model_name = dbutils.secrets.get("genai-scope", "embedding_model_name")

def get_embedding(text):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "input": text,
        "model": model_name
    }
    response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=30)
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]