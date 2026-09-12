# DEPRECATED — one-off migration script.
#
# This already set weight_current/weight_goal on the local calories.db (SQLite)
# once. Running it again is harmless (it just re-applies the same UPDATE), but
# it only ever touched the LOCAL SQLite file, never Supabase — which is why the
# weight bar wasn't showing up in production (see AUDIT.md, "Баг — вес и
# «активные калории» пропадали в проде"). That part is now fixed in
# database/db.py; for Supabase you still need to run the ALTER TABLE from
# AUDIT.md once in the Supabase SQL editor.
#
# Safe to delete: rm scratch_db_fix.py
if __name__ == "__main__":
    print("scratch_db_fix.py: already applied to local SQLite — nothing to do. Safe to delete.")
