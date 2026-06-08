import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory.vector_store import IncidentMemory

def ingest_ground_truth():
    file_path = "data/synthetic/logs.json"
    with open(file_path, "r") as f:
        data = json.load(f)
    
    memory = IncidentMemory()
    
    # Ingest the 5 hard incidents
    for inc in data["incidents"][-5:]:
        memory.store_incident(
            incident_id=inc["incident_id"],
            root_cause=inc["actual_root_cause"],
            resolution="Refer to the chain of events.",
            service=inc["affected_service"],
            summary=inc.get("actual_root_cause", "")[:100],
            human_input="",
            confidence_score=inc.get("actual_confidence", 1.0)
        )
    print("Ingested 5 hard incidents into ChromaDB.")

if __name__ == "__main__":
    ingest_ground_truth()
