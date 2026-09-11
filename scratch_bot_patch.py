import os

path = 'bot/telegram_bot.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add "➕ Добавить продукт" to main_keyboard
keyboard_old = '''        main_keyboard = ReplyKeyboardMarkup(
            [
                ["🍲 Запись приема пищи", "👨‍💼 Технический таск"],
                ["📊 Итоги за сегодня",  "💡 Советы ИИ-тренера"]
            ],'''
keyboard_new = '''        main_keyboard = ReplyKeyboardMarkup(
            [
                ["🍲 Запись приема пищи", "➕ Добавить продукт"],
                ["📊 Итоги за сегодня",  "💡 Советы ИИ-тренера"],
                ["👨‍💼 Технический таск"]
            ],'''
content = content.replace(keyboard_old, keyboard_new)

# 2. Add MODE_ADD_PRODUCT
mode_old = '''        # ── Mode keys stored in context.user_data ────────────────────────
        MODE_FOOD = "food"
        MODE_TASK = "task"'''
mode_new = '''        # ── Mode keys stored in context.user_data ────────────────────────
        MODE_FOOD = "food"
        MODE_TASK = "task"
        MODE_ADD_PRODUCT = "add_product"'''
content = content.replace(mode_old, mode_new)

# 3. Add to handle_text
text_old = '''                elif text_lower == "👨‍💼 технический таск":
                    set_mode(context, MODE_TASK)
                    response = "👨‍💼 Режим: Техническая задача.\\nНапишите или надиктуйте, что нужно исправить/добавить."'''
text_new = '''                elif text_lower == "👨‍💼 технический таск":
                    set_mode(context, MODE_TASK)
                    response = "👨‍💼 Режим: Техническая задача.\\nНапишите или надиктуйте, что нужно исправить/добавить."
                elif text_lower == "➕ добавить продукт":
                    set_mode(context, MODE_ADD_PRODUCT)
                    response = "📸 Режим: Добавление продукта.\\nОтправьте четкое фото продукта (название и таблица БЖУ на 100г)."'''
content = content.replace(text_old, text_new)

# 4. Modify handle_photo
photo_old = '''        # ── Photo handler ─────────────────────────────────────────────────
        async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text("📷 Фото получено! ИИ анализирует блюдо...")
            try:
                photo_file = await update.message.photo[-1].get_file()
                image_bytes = await photo_file.download_as_bytearray()
                caption = update.message.caption or ""
                
                response = process_user_meal_input(caption, input_type="photo", image_bytes=bytes(image_bytes))
                await update.message.reply_markdown(f"📷 **Фото блюда обработано!**\\n\\n{response}")
            except Exception as e:
                logger.error(f"Photo error: {e}")
                await update.message.reply_text(f"⚠️ Ошибка при обработке фото: {e}")'''

photo_new = '''        # ── Photo handler ─────────────────────────────────────────────────
        async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            mode = get_mode(context)
            await update.message.reply_text("📷 Фото получено! ИИ обрабатывает...")
            try:
                photo_file = await update.message.photo[-1].get_file()
                image_bytes = bytes(await photo_file.download_as_bytearray())
                caption = update.message.caption or ""
                
                if mode == MODE_ADD_PRODUCT:
                    # Send to Gemini to extract product data
                    from google import genai
                    from google.genai import types
                    import json
                    from database.db import save_custom_product
                    
                    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
                    sys_prompt = "Извлеки название продукта и КБЖУ на 100 грамм из изображения. Верни ТОЛЬКО JSON формата: {\\"product_name\\": \\"string\\", \\"calories_100g\\": float, \\"protein_100g\\": float, \\"fat_100g\\": float, \\"carbs_100g\\": float}."
                    
                    resp = client.models.generate_content(
                        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
                        contents=[
                            types.Content(role="user", parts=[types.Part.from_text(text=sys_prompt)]),
                            types.Content(role="model", parts=[types.Part.from_text(text="Understood. I will return only valid JSON without markdown blocks.")]),
                            types.Content(role="user", parts=[
                                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                                types.Part.from_text(text="Extract product nutrition info per 100g")
                            ]),
                        ],
                        config=types.GenerateContentConfig(temperature=0.0)
                    )
                    
                    text_resp = resp.text
                    if "```json" in text_resp:
                        text_resp = text_resp.split("```json")[1].split("```")[0]
                    elif "```" in text_resp:
                        text_resp = text_resp.split("```")[1].split("```")[0]
                    text_resp = text_resp.strip()
                    
                    data = json.loads(text_resp)
                    save_custom_product(
                        data["product_name"],
                        float(data["calories_100g"]),
                        float(data["protein_100g"]),
                        float(data["fat_100g"]),
                        float(data["carbs_100g"])
                    )
                    set_mode(context, None)
                    await update.message.reply_markdown(
                        f"✅ **Продукт добавлен в базу!**\\n\\n"
                        f"📦 Название: `{data['product_name']}`\\n"
                        f"🔥 Калории: {data['calories_100g']} ккал/100г\\n"
                        f"🥩 Белки: {data['protein_100g']} г/100г\\n"
                        f"🥑 Жиры: {data['fat_100g']} г/100г\\n"
                        f"🍚 Углеводы: {data['carbs_100g']} г/100г",
                        reply_markup=main_keyboard
                    )
                else:
                    response = process_user_meal_input(caption, input_type="photo", image_bytes=image_bytes)
                    await update.message.reply_markdown(f"📷 **Фото блюда обработано!**\\n\\n{response}", reply_markup=main_keyboard)
            except Exception as e:
                logger.error(f"Photo error: {e}")
                await update.message.reply_text(f"⚠️ Ошибка при обработке фото: {e}")'''

content = content.replace(photo_old, photo_new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated telegram_bot.py")
