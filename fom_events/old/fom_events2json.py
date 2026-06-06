import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import httpx

load_dotenv()
google_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(
        api_key=google_key,
    )

doc_url = "https://media.fom.ru/fom-bd/d15sn2020.pdf"  # Replace with the actual URL of your PDF

# Retrieve and encode the PDF byte
doc_data = httpx.get(doc_url).content

prompt = """
В этом pdf документе представлена таблица с событиями, которые респонденты назвали самыми значимыми.
Первый столбец содержит события. Второй столбец - цитаты респондентов, описывающие событие. Третий столбец - процент людей, назвавших это событие.
В некоторых случаях во втором столбце указаны подсобытия (как части основного события, указанного в первом столбце) с соответствующими им процентами.

Твоя задача преобразовать таблицу из этого файла в список всех событий таблицы со следующими параметрами для каждого события: название события, описание события, процент респондентов.
Этот список должен включать все события и подсобытия (если они есть во втором столбце). Название подсобытий нужно брать из второго столбца.
Описание события - это краткое саммари на основе названия из первого столбца и цитат респондентов.
"""

# Fix: Properly structure the content with Content and Parts
contents = [
    types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(
                data=doc_data,
                mime_type='application/pdf',
            ),
            types.Part.from_text(text=prompt),
        ],
    )
]
      
generate_content_config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json"
        )

response = client.models.generate_content(
        model = "gemini-2.0-flash",
        contents = contents,
        config = generate_content_config
      ,
    )

print(response.text)
