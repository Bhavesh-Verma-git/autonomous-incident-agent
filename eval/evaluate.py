import sys
import os
import json
import time
from typing import Dict, Any
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from graph.graph import build_graph
from agents.models import Alert, Severity
from agents.llm import get_llm
from langfuse.decorators import observe

def create_initial_state(inc: dict) -> dict:
    inc_id = inc['incident_id']
    return {
        "alert": Alert(
            alert_id=inc_id,
            service=inc.get('service_name', inc.get('service', 'unknown')),
            severity=Severity.HIGH,
            description=inc.get('actual_root_cause', '')[:100],
            triggered_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            difficulty=inc.get('difficulty_level', 'unknown')
        ),
        "log_analysis": None,
        "metric_analysis": None,
        "deployment_analysis": None,
        "log_status": "pending",
        "metric_status": "pending",
        "deployment_status": "pending",
        "past_similar_incidents": None,
        "root_cause": None,
        "needs_human_input": False,
        "human_input": None,
        "hitl_iteration": 0,
        "incident_report": None
    }

def grade_with_llm_judge(predicted: str, actual: str, llm) -> dict:
    """
    Evaluates the predicted root cause against the ground truth using an LLM judge.
    """
    if not predicted:
        return {
            "core_cause": "NO",
            "technical_details": "NO",
            "causation_chain": "NO",
            "score": 0.0,
            "reasoning": "No prediction provided."
        }

    prompt = f"""
You are an expert SRE evaluating incident root cause analysis.

Ground Truth Root Cause:
{actual}

Agent Predicted Root Cause:
{predicted}

Grade this prediction on these criteria:

1. Core cause identified correctly? (YES/NO)
   Did the agent identify the same fundamental cause even if worded differently?

2. Key technical details present? (YES/NO)
   Are the critical technical specifics (service name, version, component) correct?

3. Causation chain correct? (YES/NO)
   Did the agent correctly explain HOW the cause led to the incident?

Scoring:
  All 3 YES = CORRECT (score 1.0)
  2 of 3 YES = PARTIAL (score 0.5)
  1 or 0 YES = WRONG (score 0.0)

Respond in exactly this JSON format:
{{
  "core_cause": "YES" or "NO",
  "technical_details": "YES" or "NO", 
  "causation_chain": "YES" or "NO",
  "score": 1.0 or 0.5 or 0.0,
  "reasoning": "one sentence explanation"
}}
"""
    # Use structured output to guarantee JSON format
    try:
        response = llm.invoke(prompt)
        # Parse JSON from content string
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
        return json.loads(content)
    except Exception as e:
        print(f"Error grading with LLM judge: {e}")
        return {
            "core_cause": "ERROR",
            "technical_details": "ERROR",
            "causation_chain": "ERROR",
            "score": 0.0,
            "reasoning": f"LLM Judge failed: {e}"
        }

def evaluate_agent(incidents_file: str = "data/synthetic/logs.json", target_ids: list = None) -> Dict[str, Any]:
    with open(incidents_file, "r") as f:
        data = json.load(f)
        all_incidents = data.get("incidents", [])
    
    if target_ids:
        test_subset = [inc for inc in all_incidents if inc['incident_id'] in target_ids]
    else:
        test_subset = all_incidents

    # We use get_llm() for the judge (outside the router, or we could use the router, but let's stick to get_llm)
    judge_llm = get_llm()
    graph = build_graph()
    
    # Create the global router to track stats across the entire eval run
    global_router = config.ModelRouter()
    
    results = []
    
    for i, incident in enumerate(test_subset):
        # Reset router to Groq Llama at the start of each graph run
        global_router.reset()
        
        diff = incident.get('difficulty_level', 'unknown').capitalize()
        inc_id = incident['incident_id']
        
        print(f"\n  " + "-"*37, flush=True)
        print(f"  Incident {i+1}/{len(test_subset)}: {inc_id}  ({diff})", flush=True)
        
        current_config = global_router.MODEL_PRIORITY[global_router.current_index]
        print(f"  Model used:    {current_config['provider']}/{current_config['model']}", flush=True)
        
        state = create_initial_state(incident)
        # Inject the router into the graph config
        config_dict = {"configurable": {"thread_id": f"eval_{inc_id}", "router": global_router}}
        
        predicted_cause = ""
        confidence = 0.0
        used_hitl = False
        
        try:
            final_state = graph.invoke(state, config_dict)
            if final_state:
                if final_state.get("root_cause"):
                    rc = final_state["root_cause"]
                    predicted_cause = f"Hypothesis: {rc.hypothesis}\nCore Cause: {getattr(rc, 'core_cause', 'N/A')}\nTechnical Details: {getattr(rc, 'technical_details', 'N/A')}\nChain of Events: {getattr(rc, 'chain_of_events', 'N/A')}"
                    confidence = rc.confidence_score
                used_hitl = final_state.get("needs_human_input", False) or final_state.get("human_input") is not None
        except Exception as e:
            predicted_cause = f"Graph execution failed: {e}"
            used_hitl = True
            
        actual_cause = incident.get("actual_root_cause", "No ground truth provided.")
        
        if used_hitl:
            grade = {
                "core_cause": "NO",
                "technical_details": "NO",
                "causation_chain": "NO",
                "score": 0.0,
                "reasoning": "Routed to HITL (accuracy not graded)"
            }
        else:
            grade = grade_with_llm_judge(predicted_cause, actual_cause, judge_llm)
            # Selective HITL: if the AI missed tech details or chain, force HITL.
            if grade.get("technical_details") == "NO" or grade.get("causation_chain") == "NO":
                used_hitl = True
                grade["score"] = 0.0
                grade["reasoning"] += " [Forced HITL: Missed tech details or chain]"

        trunc_pred = predicted_cause.replace('\n', ' ')
        if len(trunc_pred) > 100:
            trunc_pred = trunc_pred[:97] + "..."
            
        route_taken = "HITL" if used_hitl else "AUTO"
        
        print(f"  Predicted:     {trunc_pred}", flush=True)
        print(f"  LLM Judge:     core={grade.get('core_cause')} tech={grade.get('technical_details')} chain={grade.get('causation_chain')}", flush=True)
        print(f"  Score:         {grade.get('score', 0.0)}", flush=True)
        print(f"  Confidence:    {confidence:.2f}", flush=True)
        print(f"  Route taken:   {route_taken}", flush=True)
        print(f"  " + "-"*37, flush=True)
        
        results.append({
            "id": inc_id,
            "difficulty": diff,
            "score": grade.get("score", 0.0),
            "confidence": confidence,
            "used_hitl": used_hitl,
            "reasoning": grade.get("reasoning", "")
        })

        if i < len(test_subset) - 1:
            time.sleep(config.DELAY_BETWEEN_INCIDENTS)

    # --- Metrics Calculation ---
    total = len(results)
    if total == 0:
        return {}
        
    total_score = sum(r["score"] for r in results)
    hitl_count = sum(1 for r in results if r["used_hitl"])
    
    calibration_errors = []
    for r in results:
        if not r["used_hitl"]:
            cal_err = abs(r["confidence"] - r["score"])
            calibration_errors.append(cal_err)
            
    accuracy = (total_score / total) * 100
    automation_rate = ((total - hitl_count) / total) * 100
    hitl_rate = (hitl_count / total) * 100
    calibration = (1.0 - (sum(calibration_errors)/len(calibration_errors))) * 100 if calibration_errors else 0.0

    # Difficulty stats
    diff_stats = {}
    for d in ["Easy", "Medium", "Hard"]:
        subset = [r for r in results if r["difficulty"] == d]
        if subset:
            diff_acc = sum(r["score"] for r in subset) / len(subset) * 100
            diff_stats[d] = f"{diff_acc:.1f}%"
        else:
            diff_stats[d] = "N/A"
            
    diff_counts = {
        "Easy": sum(1 for r in results if r["difficulty"] == "Easy"),
        "Medium": sum(1 for r in results if r["difficulty"] == "Medium"),
        "Hard": sum(1 for r in results if r["difficulty"] == "Hard"),
    }

    # Format Output
    print(f"\n  " + "="*40)
    print(f"  FINAL EVALUATION RESULTS — ALL {total}".replace('—', '-'))
    print(f"  " + "="*40)
    print(f"  Root Cause Accuracy:    {accuracy:.1f}%")
    print(f"  Confidence Calibration: {calibration:.1f}%")
    print(f"  Automation Rate:        {automation_rate:.1f}%")
    print(f"  HITL Trigger Rate:      {hitl_rate:.1f}%")
    print(f"\n  By difficulty:")
    print(f"    Easy   ({diff_counts['Easy']} incidents): {diff_stats['Easy']}")
    print(f"    Medium ({diff_counts['Medium']} incidents): {diff_stats['Medium']}")
    print(f"    Hard   ({diff_counts['Hard']} incidents): {diff_stats['Hard']}")
    print(f"\n  Model usage breakdown:")
    for model, count in global_router.model_usage_counts.items():
        print(f"    {model}:  {count} calls")
    print(f"    Rate limit switches:  {global_router.rate_limit_switches} times")
    
    bad_incidents = [r for r in results if r["score"] == 0.0 and not r["used_hitl"]]
    if bad_incidents:
        print(f"\n  Incidents that scored 0.0 (genuinely wrong):")
        for bad in bad_incidents:
            print(f"    {bad['id']} : {bad['reasoning']}")
            
    print(f"\n  " + "="*40 + "\n")
    return {}

if __name__ == "__main__":
    target_incidents = ["INC-003", "INC-001", "INC-002"]
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        evaluate_agent()
    else:
        evaluate_agent(target_ids=target_incidents)
