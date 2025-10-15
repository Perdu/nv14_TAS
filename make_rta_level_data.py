import pymysql
import yaml

from db_config import DB_CONFIG

# Creates the tas/level_data_rta.yml file out of a local database created with https://github.com/Perdu/n_scores/
# Quick & Dirty script, don't expect good code

# --- Database connection details ---
connection = pymysql.connect(**DB_CONFIG)

cursor = None


def fetch_level(row, col):
    level_id = row * 10 + col
    query = f"select pseudo, timestamp, score, demo from score_unique where place = 0 and level_id={level_id} and score in (select max(score) from score_unique where place = 0 and level_id={level_id});"

    cursor.execute(query)
    rows = cursor.fetchall()

    data = {}
    data[f"{row}-{col}"] = {
        "loading_time": 50,
        "Highscore": {
            "time": rows[0]["score"],
            "authors": rows[0]["pseudo"],
            "type": "rta",
            "timestamp": rows[0]["timestamp"],
            "demo": "##" + str(rows[0]["demo"]) + "#"
        }
    }

    # --- Dump to YAML file ---
    with open("tas/level_data_rta.yml", "a") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    for i in range(0, 100):
        for j in range(0, 5):
            fetch_level(i, j)
    connection.close()
