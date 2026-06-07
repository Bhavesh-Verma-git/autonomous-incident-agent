"""
tests/test_all_incidents.py

Run all 15 synthetic incidents through the pipeline to ensure 
0% crash rate and proper routing.
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.checkpoint.sqlite import SqliteSaver
from graph.graph import build_graph
from agents.models import Alert

# We'll use a temporary memory DB for the bulk test
TEST_DB = "memory/test_bulk.db"
os.makedirs("memory", exist_ok=True)

def load_all_incidents():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "synthetic", "logs.json")
    with open(path, "r") as f:
        data = json.load(f)
    return data.get("incidents", [])

def run_all():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
        
    results = []
    incidents = load_all_incidents()
    
    print(f"Loaded {len(incidents)} incidents. Running pipeline...")
    
    with SqliteSaver.from_conn_string(TEST_DB) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        
        for inc in incidents:
            inc_id = inc['incident_id']
            print(f"\n--- Processing {inc_id} ---")
            config = {"configurable": {"thread_id": inc_id}}
            
            # Create a basic initial state
            # (We only need the alert. The tools will fetch logs/metrics/deployments using inc_id)
            initial_state = {
                "alert": Alert(
                    alert_id=inc_id,
                    service=inc.get('service', 'unknown'),
                    severity="high",
                    description=inc.get('actual_root_cause', '')[:100],
                    triggered_at="2024-01-01T00:00:00Z"
                ),
                "log_analysis": None,
                "metric_analysis": None,
                "deployment_analysis": None,
                "root_cause": None,
                "needs_human_input": False,
                "human_input": None,
                "hitl_iteration": 0,
                "incident_report": None
            }
            
            try:
                # 1. Run until end or interrupt
                result = graph.invoke(initial_state, config)
                
                # Check if it paused for HITL
                paused_for_hitl = result.get('incident_report') is None
                
                if paused_for_hitl:
                    # Simulate human input to unpause
                    print(f"  [{inc_id}] Paused for HITL (Confidence: {result.get('root_cause', {}).confidence_score if hasattr(result.get('root_cause'), 'confidence_score') else result.get('root_cause', {}).get('confidence_score', 0):.2f}). Providing human input...")
                    graph.update_state(config, {"human_input": "Simulated human context for testing."})
                    result = graph.invoke(None, config)
                
                has_report = result.get('incident_report') is not None
                
                results.append({
                    "id": inc_id,
                    "status": "completed",
                    "has_report": has_report,
                    "used_hitl": paused_for_hitl
                })
                print(f"  [{inc_id}] SUCCESS -> Report: {has_report}, HITL used: {paused_for_hitl}")
                
            except Exception as e:
                import traceback
                print(f"  [{inc_id}] ERROR: {str(e)}")
                traceback.print_exc()
                results.append({
                    "id": inc_id,
                    "status": "failed",
                    "error": str(e)
                })

    print("\n" + "="*40)
    print("SUMMARY")
    print("="*40)
    
    completed = [r for r in results if r['status'] == 'completed']
    failed = [r for r in results if r['status'] == 'failed']
    
    print(f"Completed: {len(completed)}/{len(incidents)}")
    print(f"Failed: {len(failed)}/{len(incidents)}")
    
    if failed:
        print("\nFailures:")
        for f in failed:
            print(f"  - {f['id']}: {f['error']}")

if __name__ == "__main__":
    run_all()
