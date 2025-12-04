# analytics.py
import json
import os
import datetime

STATS_FILE = 'traffic_stats.json'

def record_hit():
    """
    Increments the total hit counter in a JSON file.
    Returns the new total.
    """
    if not os.path.exists(STATS_FILE):
        data = {'total_hits': 0, 'history': []}
    else:
        try:
            with open(STATS_FILE, 'r') as f:
                data = json.load(f)
        except:
            data = {'total_hits': 0, 'history': []}
    
    data['total_hits'] = data.get('total_hits', 0) + 1
    
    # Optional: Keep a simple daily log (commented out to save space/performance if not needed)
    # today = datetime.date.today().strftime("%Y-%m-%d")
    # if not data['history'] or data['history'][-1]['date'] != today:
    #     data['history'].append({'date': today, 'hits': 1})
    # else:
    #     data['history'][-1]['hits'] += 1
    
    with open(STATS_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    
    return data['total_hits']

def get_total_hits():
    """
    Returns the current total hits.
    """
    if not os.path.exists(STATS_FILE):
        return 0
    try:
        with open(STATS_FILE, 'r') as f:
            data = json.load(f)
            return data.get('total_hits', 0)
    except:
        return 0
