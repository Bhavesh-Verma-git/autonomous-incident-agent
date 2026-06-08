import json, random, pathlib, sys

# Path to the synthetic logs file
log_path = pathlib.Path(r'C:/Users/verma/Desktop/AIRP/data/synthetic/logs.json')

# Load the JSON data
try:
    data = json.loads(log_path.read_text())
except Exception as e:
    print(f'Failed to read logs.json: {e}')
    sys.exit(1)

# Define the incident IDs that were failing (require HITL)
fails = {'INC-016', 'INC-017', 'INC-018', 'INC-019'}

def has_consecutive_fails(incidents):
    """Return True if any two failing incidents are adjacent."""
    for i in range(len(incidents) - 1):
        if incidents[i]['incident_id'] in fails and incidents[i+1]['incident_id'] in fails:
            return True
    return False

max_attempts = 1000
attempt = 0
while attempt < max_attempts:
    random.shuffle(data['incidents'])
    if not has_consecutive_fails(data['incidents']):
        break
    attempt += 1
else:
    print('Could not find a shuffle without consecutive fails after many attempts.')
    sys.exit(1)

# Write the shuffled data back to the file
log_path.write_text(json.dumps(data, indent=2))
print('Shuffling completed successfully.')
