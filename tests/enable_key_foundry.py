import json
import subprocess
 
subscription_id = "f17b9f1d-4088-479a-acb6-6dbf870ca4dc"
resource_group = "rg-mano-northcentralus"
foundry_name = "ai-account-cg4svtxvpep4q"
location = "northcentralus"
 
# Uses 2025-04-01-preview to support allowProjectManagement
foundry_url = (
    f"https://management.azure.com/subscriptions/{subscription_id}"
    f"/resourceGroups/{resource_group}"
    f"/providers/Microsoft.CognitiveServices/accounts/{foundry_name}"
    "?api-version=2025-04-01-preview"
)
 
foundry_body = json.dumps(
    {
        "kind": "AIServices",
        "sku": {"name": "S0"},
        "location": f"{location}",
        "identity": {"type": "SystemAssigned"},
        "tags": {
            "SecurityControl": "Ignore",
        },
        "properties": {
            "disableLocalAuth": False,
        },
    }
)
 
print(f"📌 Step 1: Modified Foundry resource: {foundry_name}")
print("   Type: SpeechServices")
print("   disableLocalAuth: False")
print("   tags: SecurityControl=Ignore")
 
result = subprocess.run(
    ["az", "rest", "--method", "PATCH", "--url", foundry_url, "--body", foundry_body],
    capture_output=True,
    text=True,
)
 
if result.returncode != 0:
    raise RuntimeError(f"Foundry resource creation failed: {result.stderr}")
 
print("✅ Foundry resource created")
foundry_info = json.loads(result.stdout)
foundry_id = foundry_info.get("id", "")
print(f"   Foundry ID: {foundry_id}")
 
properties = foundry_info.get("properties", {})
allow_project = properties.get("allowProjectManagement")
disable_local_auth = properties.get("disableLocalAuth")
 
print(f"    disableLocalAuth: {disable_local_auth}")