import pytest
import shutil
import os
from memory.vector_store import IncidentMemory

@pytest.fixture
def temp_memory():
    test_db = "memory/test_chroma_pytest"
    try:
        if os.path.exists(test_db):
            shutil.rmtree(test_db)
    except Exception:
        pass
    
    memory = IncidentMemory(persist_directory=test_db, collection_name="test_collection")
    
    # Store some data
    memory.store_incident(
        incident_id="PAST-001",
        summary="High error rate on checkout due to expired SSL cert.",
        root_cause="The SSL certificate on the payment gateway expired.",
        human_input="I renewed the certs manually."
    )
    
    yield memory
    
    # Cleanup after test
    # (Chroma DB holds a file lock, so Windows sometimes complains about rmtree.
    # We will try our best to clean up, but ignore errors)
    try:
        shutil.rmtree(test_db, ignore_errors=True)
    except:
        pass

def test_semantic_search_finds_match(temp_memory):
    results = temp_memory.find_similar_incidents("High error rate on checkout due to expired SSL cert.", n=1)
    assert len(results["ids"][0]) > 0


    assert results["ids"][0][0] == "PAST-001"

def test_distance_threshold_filters_out_garbage(temp_memory):
    # This query is completely unrelated to SSL certs.
    # It should be filtered out by the SIMILARITY_THRESHOLD logic we added.
    results = temp_memory.find_similar_incidents("CSS styling is broken on the mobile homepage when using Safari.", n=1)
    assert len(results["ids"][0]) == 0
