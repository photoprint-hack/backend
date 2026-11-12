import csv
import json
from pathlib import Path


async def test_all_supplied_json_and_csv_samples_import_and_replay(client, minimal_admin):
    root = Path(__file__).parents[1] / "data/mock"
    for source in ["crm", "erp", "finance", "support", "hr"]:
        payload = json.loads((root / (source + ".json")).read_text())
        with (root / (source + ".csv")).open(newline="") as stream:
            converted = [{**row, "data": json.loads(row["data"])} for row in csv.DictReader(stream)]
        assert converted == payload["records"]
        response = await client.post(
            "/api/v1/integrations/" + source + "/import", headers=minimal_admin, json=payload
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["failed"] == 0, response.text
        repeated = await client.post(
            "/api/v1/integrations/" + source + "/import", headers=minimal_admin, json={"records": converted}
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["data"]["failed"] == 0, repeated.text
        assert repeated.json()["data"]["inserted"] == 0, repeated.text
