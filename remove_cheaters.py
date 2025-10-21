import pymysql

from db_config import DB_CONFIG

# Remove cheaters from local database

connection = pymysql.connect(**DB_CONFIG)

cursor = None

# From https://forum.droni.es/viewtopic.php?p=176079#p176079 + discussion with community
CHEATERS = ['ANGERFIST', 'kryX-orange', 'L3X', 'Bonzai', 'naem', 'crappitrash', 'Goo', 'Sp33dy', 'pokemaniac1342', 'ACEOFSPADEWINS', 'Vegeta', 'BAS3', 'cheese_god', 'fuckingyourdad', 'fuckingyourmom', 'fuckingcrappitrash', 'VotedStraw61372', 'Donald_J_Trump']

if __name__ == "__main__":
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    for cheater in CHEATERS:
        print(f"Removing {cheater}")
        rows_deleted = cursor.execute(f"delete from score_unique where pseudo = '{cheater}'")
        print(f"→ Deleted {rows_deleted} rows.")
    connection.close()
