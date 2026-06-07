import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import numpy as np
from typing import Dict, Any
from datetime import datetime, timezone
from langchain_huggingface import HuggingFaceEmbeddings
import config

from graph.graph import build_graph
from agents.models import Alert, Severity
from langfuse.decorators import observe

def create_initial_state(inc: dict) -> dict:
    inc_id = inc['incident_id']
    return {
        "alert": Alert(
            alert_id=inc_id,
            service=inc.get('service_name', inc.get('service', 'unknown')),
            severity=Severity.HIGH,
            description=inc.get('actual_root_cause', '')[:100],
            triggered_at=datetime(2024, 1, 1, tzinfo=timezone.utc)
        ),
        "log_analysis": None,
        "metric_analysis": None,
        "deployment_analysis": None,
        "past_similar_incidents": None,
        "root_cause": None,
        "needs_human_input": False,
        "human_input": None,
        "hitl_iteration": 0,
        "incident_report": None
    }

def calculate_semantic_similarity(actual: str, predicted: str, embeddings) -> float:
    """
    Calculates semantic similarity between ground truth and predicted root cause.
    """
    if not predicted:
        return 0.0
    vec1 = embeddings.embed_query(actual)
    vec2 = embeddings.embed_query(predicted)
    # Cosine similarity
    dot = np.dot(vec1, vec2)
    norm = np.linalg.norm(vec1) * np.linalg.norm(vec2)
    return float(dot / norm) if norm > 0 else 0.0

@observe(name="evaluation_run")
def evaluate_agent(incidents_file: str = "data/synthetic/logs.json") -> Dict[str, Any]:
    """
    Runs the agent against all incidents and calculates evaluation metrics.
    """
    with open(incidents_file, "r") as f:
        data = json.load(f)
        incidents = data.get("incidents", [])
        
    embeddings = HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)
    graph = build_graph()
    
    results = []
    
    # We will evaluate the first 5 to save time and API costs for the test
    test_subset = incidents[:5] 
    
    for incident in test_subset:
        print(f"Evaluating {incident['incident_id']}...")
        
        state = create_initial_state(incident)
        config_dict = {"configurable": {"thread_id": f"eval_{incident['incident_id']}"}}
        
        # Run the graph
        try:
            # We run until interrupt or completion
            final_state = graph.invoke(state, config_dict)
            
            # Extract data
            predicted_cause = ""
            confidence = 0.0
            if final_state and final_state.get("root_cause"):
                predicted_cause = final_state["root_cause"].hypothesis
                confidence = final_state["root_cause"].confidence_score
                
            results.append({
                "id": incident["incident_id"],
                "category": incident.get("service", incident.get("service_name", "unknown")),
                "actual_cause": incident["actual_root_cause"],
                "predicted_cause": predicted_cause,
                "confidence": confidence,
                "used_hitl": final_state.get("human_input") is not None
            })
        except Exception as e:
            print(f"Failed on {incident['incident_id']}: {e}")

    # --- Metrics Calculation ---
    
    total = len(results)
    if total == 0:
        return {"accuracy": 0.0, "automation_rate": 0.0, "calibration": 0.0, "false_positive_rate": 0.0, "by_category": {}}
        
    correct_count = 0
    hitl_count = 0
    false_positive_hitl = 0
    calibration_errors = []
    category_scores = {}
    
    for r in results:
        sim = calculate_semantic_similarity(r["actual_cause"], r["predicted_cause"], embeddings)
        is_correct = sim > 0.85
        
        if is_correct:
            correct_count += 1
            
        if r["used_hitl"]:
            hitl_count += 1
            # False positive HITL: the agent was correct but STILL triggered HITL
            if is_correct:
                false_positive_hitl += 1
        else:
            # Calibration error: absolute difference between confidence and correctness (1 or 0)
            cal_err = abs(r["confidence"] - (1.0 if is_correct else 0.0))
            calibration_errors.append(cal_err)
            
        # Category tracking
        cat = r["category"]
        if cat not in category_scores:
            category_scores[cat] = {"total": 0, "correct": 0}
        category_scores[cat]["total"] += 1
        if is_correct:
            category_scores[cat]["correct"] += 1

    accuracy = correct_count / total
    automation_rate = (total - hitl_count) / total
    fp_rate = false_positive_hitl / hitl_count if hitl_count > 0 else 0.0
    calibration = 1.0 - (sum(calibration_errors)/len(calibration_errors) if calibration_errors else 0.0)
    
    by_category = {}
    for cat, stats in category_scores.items():
        by_category[cat] = stats["correct"] / stats["total"]

    return {
        "accuracy": accuracy,
        "automation_rate": automation_rate,
        "calibration": calibration,
        "false_positive_rate": fp_rate,
        "by_category": by_category
    }

if __name__ == "__main__":
    res = evaluate_agent()
    print("\n" + "="*50)
    print("EVALUATION RESULTS")
    print("="*50)
    print(f"Root Cause Accuracy:    {res['accuracy']:.1%}")
    print(f"Automation Rate:        {res['automation_rate']:.1%}")
    print(f"Confidence Calibration: {res['calibration']:.1%}")
    print(f"False Positive HITL:    {res['false_positive_rate']:.1%}")
    print("\nBy Category:")
    for category, score in res['by_category'].items():
        print(f"  {category}: {score:.1%}")
    print("="*50)
