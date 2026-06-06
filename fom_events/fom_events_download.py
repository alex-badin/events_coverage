import os
import requests
from datetime import datetime
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("download_reports.log"),
        logging.StreamHandler()
    ]
)

def download_pdf(url, save_path):
    """Download a PDF file from the given URL and save it to the specified path."""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()  # Raise an exception for HTTP errors
        
        # Check if the content is a PDF (simple check)
        content_type = response.headers.get('Content-Type', '')
        if 'application/pdf' not in content_type and len(response.content) < 5000:
            logging.warning(f"URL {url} doesn't seem to be a valid PDF. Skipping.")
            return False
        
        # Save the file
        with open(save_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
        
        logging.info(f"Successfully downloaded: {url}")
        return True
    
    except requests.exceptions.RequestException as e:
        if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 404:
            logging.debug(f"File not found: {url}")
        else:
            logging.error(f"Error downloading {url}: {str(e)}")
        return False

def main():
    # Create directory for saving PDFs
    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloaded_reports")
    os.makedirs(save_dir, exist_ok=True)
    
    # File to save valid PDF links
    links_file = os.path.join(save_dir, "valid_pdf_links.txt")
    valid_links = []
    
    # Base URL
    base_url = "https://media.fom.ru/fom-bd/d{week}sn{year}.pdf"
    
    # Current year
    current_year = datetime.now().year
    
    # Download reports from 2020 to current year
    for year in range(2020, current_year + 1):
        # Try all possible week numbers (1-53)
        for week in range(1, 54):
            # Create a set of week formats to try (automatically handles duplicates)
            week_formats = {f"{week:02d}", f"{week}"}  # Will be 1 item for weeks ≥ 10
            
            for week_str in week_formats:
                # Construct URL
                url = base_url.format(week=week_str, year=year)
                
                # Construct save path
                filename = f"fom_report_{year}_week{week_str}.pdf"
                save_path = os.path.join(save_dir, filename)
                
                # Skip if file already exists
                if os.path.exists(save_path):
                    logging.info(f"File already exists: {save_path}")
                    valid_links.append(url)  # Add to valid links if already downloaded
                    continue
                
                # Download the file
                success = download_pdf(url, save_path)
                
                # If download successful, add to valid links and move to next week
                if success:
                    valid_links.append(url)
                    break  # No need to try the other format if this one worked
                elif os.path.exists(save_path):
                    # Remove empty or invalid files
                    os.remove(save_path)
                
                # Add a small delay to avoid overwhelming the server
                time.sleep(1)
    
    # Save all valid links to a text file
    with open(links_file, 'w') as f:
        for link in valid_links:
            f.write(f"{link}\n")
    
    logging.info(f"Saved {len(valid_links)} valid PDF links to {links_file}")

if __name__ == "__main__":
    logging.info("Starting PDF reports download")
    main()
    logging.info("Download process completed")