import os

path = 'agents/teamlead_agent.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'def process_food_input(self, raw_text: str, input_type: str = "text") -> str:',
    'def process_food_input(self, raw_text: str, input_type: str = "text", image_bytes: bytes = None) -> str:'
)
content = content.replace(
    'return self.process_food_input(raw_text, input_type)',
    'return self.process_food_input(raw_text, input_type, image_bytes)'
)
content = content.replace(
    'llm_meals = ingestion_agent._parse_llm(raw_text)',
    'llm_meals = ingestion_agent._parse_llm(raw_text, image_bytes=image_bytes)'
)
content = content.replace(
    'parsed_items = ingestion_agent.parse(raw_text)',
    'parsed_items = ingestion_agent.parse(raw_text, image_bytes=image_bytes)'
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

path2 = 'agents/ingestion_agent.py'
with open(path2, 'r', encoding='utf-8') as f:
    content2 = f.read()

content2 = content2.replace(
    'def parse(self, raw_input: str) -> List[Dict[str, Any]]:',
    'def parse(self, raw_input: str, image_bytes: bytes = None) -> List[Dict[str, Any]]:'
)
content2 = content2.replace(
    'llm_meals = self._parse_llm(raw_input)',
    'llm_meals = self._parse_llm(raw_input, image_bytes=image_bytes)'
)
content2 = content2.replace(
    'def _parse_llm(self, raw_input: str) -> List[Dict[str, Any]]:',
    'def _parse_llm(self, raw_input: str, image_bytes: bytes = None) -> List[Dict[str, Any]]:'
)

# Insert image_bytes handling for Gemini
gemini_block_old = '''                resp = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Content(role="user",  parts=[types.Part(text=sys_prompt)]),
                        types.Content(role="model", parts=[types.Part(text="Understood. I will return only valid JSON.")]),
                        types.Content(role="user",  parts=[types.Part(text=raw_input)]),
                    ],'''

gemini_block_new = '''                user_parts = []
                if image_bytes:
                    user_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                user_parts.append(types.Part.from_text(text=raw_input or "Что на этом фото?"))

                resp = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Content(role="user",  parts=[types.Part.from_text(text=sys_prompt)]),
                        types.Content(role="model", parts=[types.Part.from_text(text="Understood. I will return only valid JSON.")]),
                        types.Content(role="user",  parts=user_parts),
                    ],'''

content2 = content2.replace(gemini_block_old, gemini_block_new)

with open(path2, 'w', encoding='utf-8') as f:
    f.write(content2)

print("Patched teamlead_agent.py and ingestion_agent.py")
