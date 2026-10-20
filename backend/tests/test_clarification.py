# backend/tests/test_clarification.py
from contracts.enums import ActionStatus, ToolName


def test_t05_multi_turn_clarification_and_draft_abandonment(client):
  """Tests multi-turn clarification sequence and 'never mind' abandonment:

  Turn 1: 'Transfer to Bob' -> Needs clarification (no proposal yet)
  Turn 2: '500' -> Combines with Turn 1, generates proposal! Turn 3: 'never mind'
  -> Cancels draft and clears memory.
  """
  conv_id = "c_clarify_test"

  # Turn 1: Missing amount
  r1 = client.post(
      "/api/v1/chat",
      json={"conversation_id": conv_id, "message": "Transfer to Bob"},
      headers={"X-Demo-User-Id": "usr_demo_01"},
  )
  assert r1.status_code == 200
  data1 = r1.json()
  assert "How much" in data1["reply"]
  assert len(data1["actions"]) == 0  # No action created yet!

  # Turn 2: User provides the amount ("500")
  r2 = client.post(
      "/api/v1/chat",
      json={"conversation_id": conv_id, "message": "500"},
      headers={"X-Demo-User-Id": "usr_demo_01"},
  )
  assert r2.status_code == 200
  data2 = r2.json()
  assert data2["status"] == ActionStatus.PENDING_CONFIRMATION.value
  assert len(data2["actions"]) == 1
  assert data2["actions"][0]["tool"] == ToolName.REQUEST_TRANSFER.value
  assert data2["actions"][0]["arguments"]["amount"] == "500.00"

  # Turn 3: Abandonment test ("never mind")
  r3 = client.post(
      "/api/v1/chat",
      json={"conversation_id": conv_id, "message": "never mind"},
      headers={"X-Demo-User-Id": "usr_demo_01"},
  )
  assert r3.status_code == 200
  assert "cancelled" in r3.json()["reply"].lower()