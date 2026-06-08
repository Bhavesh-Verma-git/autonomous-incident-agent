import json
import uuid

def augment_logs():
    file_path = "data/synthetic/logs.json"
    with open(file_path, "r") as f:
        data = json.load(f)

    # Base for hard incidents
    new_incidents = [
        {
            "incident_id": "INC-020",
            "difficulty_level": "hard",
            "actual_root_cause": "Hypothesis: The root cause of the incident is a memory leak caused by the deployment of v2.5.0, leading to OOM kills.\nCore Cause: Memory leak causing Out of Memory (OOM) kills\nTechnical Details: service 'image-processor', version 'v2.5.0', metric 'memory_percent' hitting 100%\nChain of Events: The deployment of v2.5.0 introduced an unoptimized image caching mechanism. This caused the memory to gradually fill up, eventually exhausting the container's RAM. The OS then triggered OOM kills on the pods, resulting in dropped requests and increased error rates.",
            "actual_confidence": 0.85,
            "timestamp": "2024-02-01T10:00:00Z",
            "affected_service": "image-processor",
            "recent_deployments": [
                {
                    "deploy_id": "DEP-9001",
                    "service": "image-processor",
                    "version": "v2.5.0",
                    "deployed_at": "2024-02-01T08:00:00Z",
                    "deployed_by": "auto@company.com",
                    "commit_message": "feat: new image cache",
                    "files_changed": ["src/cache.py"],
                    "rollback_available": True,
                    "status": "success"
                }
            ],
            "logs": [
                {"timestamp": "2024-02-01T09:45:00Z", "level": "WARN", "service": "image-processor", "message": "Memory utilization at 95%"} ,
                {"timestamp": "2024-02-01T09:55:00Z", "level": "ERROR", "service": "image-processor", "message": "Process killed by OOM killer"} 
            ],
            "metrics": {
                "error_rate_percent": 15.0,
                "memory_percent": 100.0,
                "cpu_percent": 40.0
            }
        },
        {
            "incident_id": "INC-021",
            "difficulty_level": "hard",
            "actual_root_cause": "Hypothesis: The incident was caused by Redis connection exhaustion due to a misconfigured timeout setting in v3.1.2.\nCore Cause: Redis connection pool exhaustion\nTechnical Details: service 'session-service', version 'v3.1.2', Redis connection timeout set too high\nChain of Events: The release of v3.1.2 included a change to the Redis client configuration, increasing the timeout to an excessively high value. When a minor network blip occurred, connections hung open instead of dropping. This quickly exhausted the available connection pool, preventing new sessions from being created and causing 500 errors for users.",
            "actual_confidence": 0.88,
            "timestamp": "2024-02-02T11:00:00Z",
            "affected_service": "session-service",
            "recent_deployments": [
                {
                    "deploy_id": "DEP-9002",
                    "service": "session-service",
                    "version": "v3.1.2",
                    "deployed_at": "2024-02-02T10:00:00Z",
                    "deployed_by": "dev@company.com",
                    "commit_message": "fix: increase redis timeout",
                    "files_changed": ["config/redis.yml"],
                    "rollback_available": True,
                    "status": "success"
                }
            ],
            "logs": [
                {"timestamp": "2024-02-02T10:50:00Z", "level": "WARN", "service": "session-service", "message": "Redis connection pool at 90% capacity"},
                {"timestamp": "2024-02-02T10:55:00Z", "level": "ERROR", "service": "session-service", "message": "RedisTimeoutError: Unable to acquire connection from pool"}
            ],
            "metrics": {
                "error_rate_percent": 25.0,
                "redis_connections": 5000,
                "latency_p99_ms": 15000
            }
        },
        {
            "incident_id": "INC-022",
            "difficulty_level": "hard",
            "actual_root_cause": "Hypothesis: A rogue background job in the reporting-service caused high CPU utilization and starved the main API threads.\nCore Cause: Thread starvation due to background job\nTechnical Details: service 'reporting-service', background cron job consuming 100% CPU, API threads blocked\nChain of Events: A scheduled cron job for generating monthly reports started running. Due to an unindexed database query within the job, it consumed excessive CPU cycles and held onto the Global Interpreter Lock (GIL) / CPU cores for too long. This starved the main HTTP worker threads, causing incoming API requests to queue up and eventually time out with 503 errors.",
            "actual_confidence": 0.82,
            "timestamp": "2024-02-03T01:00:00Z",
            "affected_service": "reporting-service",
            "recent_deployments": [],
            "logs": [
                {"timestamp": "2024-02-03T00:55:00Z", "level": "INFO", "service": "reporting-service", "message": "Starting monthly report generation job"},
                {"timestamp": "2024-02-03T01:00:00Z", "level": "ERROR", "service": "reporting-service", "message": "HTTP 503: Service Unavailable. Worker queue full."}
            ],
            "metrics": {
                "error_rate_percent": 100.0,
                "cpu_percent": 100.0,
                "queue_depth": 5000
            }
        },
        {
            "incident_id": "INC-023",
            "difficulty_level": "hard",
            "actual_root_cause": "Hypothesis: An external API outage at Stripe caused payment processing to fail, resulting in cascading timeouts.\nCore Cause: External dependency outage (Stripe)\nTechnical Details: service 'payment-gateway', Stripe API returning 502 Bad Gateway\nChain of Events: The external payment provider, Stripe, experienced a regional outage. Our payment-gateway service attempted to process payments but received 502 Bad Gateway errors. Because the fallback mechanism was misconfigured, these requests took the full 30-second timeout before failing, exhausting our internal thread pool and causing a cascade of failures upstream.",
            "actual_confidence": 0.95,
            "timestamp": "2024-02-04T14:00:00Z",
            "affected_service": "payment-gateway",
            "recent_deployments": [],
            "logs": [
                {"timestamp": "2024-02-04T13:50:00Z", "level": "ERROR", "service": "payment-gateway", "message": "Stripe API error: 502 Bad Gateway"},
                {"timestamp": "2024-02-04T13:58:00Z", "level": "ERROR", "service": "payment-gateway", "message": "Thread pool exhausted waiting for upstream responses"}
            ],
            "metrics": {
                "error_rate_percent": 45.0,
                "external_api_latency_ms": 30000,
                "active_threads": 1000
            }
        },
        {
            "incident_id": "INC-024",
            "difficulty_level": "hard",
            "actual_root_cause": "Hypothesis: A database schema migration locked a critical table, blocking all read/write operations.\nCore Cause: Database table lock during migration\nTechnical Details: service 'user-service', version 'v4.0.1', ALTER TABLE statement blocking queries\nChain of Events: The deployment of v4.0.1 included a database migration script that added a new column with a default value to the 'users' table. In PostgreSQL, doing this on a large table requires a full table rewrite, which acquired an exclusive lock. This lock blocked all incoming read and write queries to the table. As requests queued up waiting for the lock, the application server hit its maximum connection limit and began returning 500 Internal Server Error to clients.",
            "actual_confidence": 0.89,
            "timestamp": "2024-02-05T03:00:00Z",
            "affected_service": "user-service",
            "recent_deployments": [
                {
                    "deploy_id": "DEP-9005",
                    "service": "user-service",
                    "version": "v4.0.1",
                    "deployed_at": "2024-02-05T02:50:00Z",
                    "deployed_by": "dba@company.com",
                    "commit_message": "db: add preferences column",
                    "files_changed": ["migrations/005_add_prefs.sql"],
                    "rollback_available": False,
                    "status": "success"
                }
            ],
            "logs": [
                {"timestamp": "2024-02-05T02:51:00Z", "level": "INFO", "service": "user-service", "message": "Starting DB migration 005_add_prefs.sql"},
                {"timestamp": "2024-02-05T02:55:00Z", "level": "WARN", "service": "user-service", "message": "Query took longer than 5000ms: SELECT * FROM users"},
                {"timestamp": "2024-02-05T02:58:00Z", "level": "ERROR", "service": "user-service", "message": "Lock wait timeout exceeded; try restarting transaction"}
            ],
            "metrics": {
                "error_rate_percent": 80.0,
                "db_active_locks": 1,
                "db_waiting_queries": 450
            }
        }
    ]

    data["incidents"].extend(new_incidents)
    
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    augment_logs()
    print("Added 5 new hard incidents to logs.json")
