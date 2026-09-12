# DEPRECATED — one-off migration script.
#
# This is the script that originally introduced the duplicate
# save_custom_product / get_custom_product definitions in database/db.py
# (see AUDIT.md, "Баг в database/db.py — дублирующиеся функции"). That has
# since been cleaned up to a single consolidated implementation. This script
# has been neutered so it can never re-introduce the duplicate-definition bug
# if run again by accident.
#
# Safe to delete: rm scratch_db_patch.py
if __name__ == "__main__":
    print("scratch_db_patch.py: neutered — the duplicate-function bug it caused has been fixed. Safe to delete.")
