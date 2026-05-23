import asyncio
import httpx
from uuid import uuid4

async def main():
    base_url = "http://localhost:4115"
    
    # 1) Busca o agent card para confirmar que o servidor está rodando
    async with httpx.AsyncClient() as http:
        card_resp = await http.get(f"{base_url}/.well-known/agent-card.json")
        card_resp.raise_for_status()
        card = card_resp.json()
        print(f"✓ Agente conectado: {card['name']} v{card['version']}\n")

    # 2) Monta o payload JSON-RPC
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": "Create an outline for a blog post about Python async programming"
                    }
                ],
                "messageId": str(uuid4()),
                "contextId": str(uuid4()),
            }
        }
    }

    # 3) Envia e imprime a resposta
    async with httpx.AsyncClient(timeout=60.0) as http:
        resp = await http.post(base_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    if "error" in data:
        print(f"✗ Erro RPC: {data['error']}")
        return

    result = data.get("result", {})
    
    # Extrai o texto da resposta
    parts = (
        result.get("parts")                          # resposta direta
        or result.get("message", {}).get("parts")    # resposta encapsulada
        or []
    )
    
    for part in parts:
        if part.get("kind") == "text":
            print(part["text"])

asyncio.run(main())