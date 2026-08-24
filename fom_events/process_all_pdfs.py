import os
import json
import yaml
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
import httpx
import time
from tqdm import tqdm

# This script and all the files it reads and writes live in fom_events/.
HERE = Path(__file__).resolve().parent

def process_pdf_link(pdf_url, client, prompt, model):
    """Process a single PDF link and return the extracted content"""
    try:
        # Extract filename from URL
        filename = os.path.basename(pdf_url)
        
        # Retrieve and encode the PDF bytes
        doc_data = httpx.get(pdf_url).content
        
        # Use the prompt passed as a parameter
        
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
            model=model,
            contents=contents,
            config=generate_content_config,
        )
        
        return response.text
    except Exception as e:
        print(f"Error processing {pdf_url}: {str(e)}")
        return None

def main():
    # Load environment variables
    load_dotenv()
    google_key = os.environ.get("GEMINI_API_KEY")
    
    # Load prompt from YAML file
    config_path = HERE / "config.yaml"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            prompt = config.get('prompt_detailed')
            model = config.get('model')
    else:
        print(f"Warning: Config file not found at {config_path}. Using default prompt and model.")
        prompt = """
        В этом pdf документе представлена таблица с событиями, которые респонденты назвали самыми значимыми.
        Первый столбец содержит название события. Второй столбец - цитаты респондентов, описывающие событие. Третий столбец - процент людей, назвавших это событие.

        Твоя задача преобразовать таблицу из этого файла в список всех событий таблицы со следующими параметрами: название события, цитаты, процент респондентов.
        """
        model = "gemini-2.0-flash"
    
    if not google_key:
        print("Error: GEMINI_API_KEY not found in environment variables")
        return
    
    if not prompt:
        print("Error: prompt_detailed not found in config.yaml")
        return
    
    # Initialize Gemini client
    client = genai.Client(api_key=google_key)
    
    # Path to the file with PDF links
    links_file = HERE / "downloaded_reports" / "valid_pdf_links.txt"
    
    # Path for the output JSON file
    output_file = HERE / "processed_events" / "processed_events.json"
    
    # Check if links file exists
    if not links_file.exists():
        print(f"Error: Links file not found at {links_file}")
        return
    
    # Read PDF links from file
    with open(links_file, 'r') as f:
        pdf_links = [line.strip() for line in f if line.strip()]
    
    # Load existing results if the file exists
    results = {}
    if output_file.exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
            print(f"Loaded {len(results)} existing results from {output_file}")
        except json.JSONDecodeError:
            print(f"Error loading existing results, starting fresh")
    
    # Process each PDF link and store results
    progress_bar = tqdm(pdf_links, desc="Processing PDFs")
    for pdf_url in progress_bar:
        filename = os.path.basename(pdf_url)
        
        # Skip if already processed
        if filename in results:
            progress_bar.set_description(f"Skipping {filename} - already processed")
            continue
            
        progress_bar.set_description(f"Processing {filename}")
        result = process_pdf_link(pdf_url, client, prompt, model)
        
        if result:
            try:
                # Try to parse the result as JSON
                parsed_result = json.loads(result)
                results[filename] = parsed_result
            except json.JSONDecodeError:
                # If not valid JSON, store as text
                results[filename] = result
            
            # Save results after each successful processing
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            progress_bar.set_postfix({"Files processed": len(results)})
        
        # Add a delay to avoid rate limiting (except for the last item)
        if pdf_url != pdf_links[-1]:
            time.sleep(2)  # 2-second delay between requests
    
    print(f"Processing complete. Results saved to {output_file}")

if __name__ == "__main__":
    main()