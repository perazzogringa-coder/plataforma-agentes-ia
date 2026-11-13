import asyncio
import json

from backend.agents_sdk.tools.human_handoff_tools import create_human_handoff_tools


def test_catalog_handoff_refuses_an_image_without_confirmed_selection():
    tool = create_human_handoff_tools(
        company_id=2,
        targets=[
            {
                "queue_key": "separacao_pedido",
                "queue_name": "Separação",
                "assignment": {"requireCatalogSelectionConfirmation": True},
            }
        ],
    )[0]

    result = asyncio.run(tool.on_invoke_tool(None, json.dumps({
        "reason": "cliente enviou uma imagem",
        "queue_key": "separacao_pedido",
        "catalog_selection_confirmed": False,
        "catalog_selection_evidence": "",
    })))

    assert result["success"] is False
    assert result["error"] == "catalog_selection_not_confirmed"
