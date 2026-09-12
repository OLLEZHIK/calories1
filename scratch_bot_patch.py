# DEPRECATED — one-off migration script.
#
# This patch has already been applied to bot/telegram_bot.py (the "Добавить
# продукт" button, MODE_ADD_PRODUCT mode, and the photo-based product lookup
# are all already live in that file). Running this script again would have no
# effect (its string replacements no longer match the current file content),
# so it has been neutered rather than left to silently do nothing on rerun.
#
# Safe to delete: rm scratch_bot_patch.py
if __name__ == "__main__":
    print("scratch_bot_patch.py: already applied — nothing to do. Safe to delete.")
