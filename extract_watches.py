#!/usr/bin/env python3
import json
import os
import time
import random
from typing import Dict, List, Optional
from playwright.sync_api import sync_playwright, Page, TimeoutError

# Constants
MAX_RETRIES = 3
DATA_DIR = "./data"
BRANDS_JSON = f"{DATA_DIR}/brands.json"
WATCHES_JSON = f"{DATA_DIR}/watches.json"
BATCH_SIZE = 10  # Save batch of watches to avoid data loss in case of errors

def polite_delay():
    """Add a random delay between requests to avoid overloading the server."""
    delay = random.uniform(2, 5)
    time.sleep(delay)

def load_brands(filename=BRANDS_JSON):
    """Load brand data from JSON file."""
    if not os.path.exists(filename):
        print(f"Brands file {filename} not found.")
        return []
    
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_watches_to_json(watches, filename=WATCHES_JSON):
    """Save watch data to a JSON file."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(watches, f, indent=2, ensure_ascii=False)
    
    print(f"Watch data ({len(watches)} watches) saved to {filename}")

def extract_specs(page: Page) -> Dict[str, str]:
    """Extract specifications (key-value pairs) from watch detail page."""
    specs = {}
    
    # Try to find the specs tables
    tables_selectors = [
        "#js-200cae34-2927-48bc-ad55-f54431064ebf-0 > section > div > div:nth-child(1) > table",
        "#js-200cae34-2927-48bc-ad55-f54431064ebf-0 > section > div > div:nth-child(2) > table",
        "table.technical-details",  # More general fallback
        "table"  # Most general fallback
    ]
    
    for selector in tables_selectors:
        try:
            tables = page.query_selector_all(selector)
            if tables:
                for table in tables:
                    rows = table.query_selector_all("tbody > tr")
                    for row in rows:
                        # Try different selectors for key and value
                        key_element = row.query_selector("th") or row.query_selector("td:first-child")
                        value_element = row.query_selector("td:last-child") or row.query_selector("td:nth-child(2)")
                        
                        if key_element and value_element:
                            key = key_element.text_content().strip()
                            value = value_element.text_content().strip()
                            if key:
                                specs[key] = value
        except Exception as e:
            print(f"Error extracting specs with selector {selector}: {e}")
    
    return specs

def extract_description(page: Page) -> str:
    """Extract watch description from detail page."""
    description = ""
    
    # Try different selectors for description
    description_selectors = [
        ".description-text",
        ".article-description",
        ".dealer-listing__description", # Another possible selector
        ".detail-page__description"     # Another possible selector
    ]
    
    for selector in description_selectors:
        try:
            desc_element = page.query_selector(selector)
            if desc_element:
                description = desc_element.text_content().strip()
                if description:
                    break
        except Exception as e:
            print(f"Error extracting description with selector {selector}: {e}")
    
    return description

def process_watch_detail(page: Page, watch_url: str) -> Optional[Dict]:
    """Process a watch detail page and extract all required information."""
    try:
        # Navigate to the watch detail page
        page.goto(watch_url)
        page.wait_for_load_state("networkidle")
        
        # Extract watch name
        watch_name = ""
        name_selectors = [
            "#detail-page-dealer > section.data.m-b-7.m-b-md-9 > div > div > div.col-xs-24.col-sm-12.col-md-10 > div:nth-child(2) > h1 > span",
            "h1 span",  # More general fallback
            "h1"        # Most general fallback
        ]
        
        for selector in name_selectors:
            try:
                name_element = page.query_selector(selector)
                if name_element:
                    watch_name = name_element.text_content().strip()
                    if watch_name:
                        break
            except Exception:
                continue
        
        # Extract price
        price = ""
        price_selectors = [
            "#detail-page-dealer > section.data.m-b-7.m-b-md-9 > div > div > div.col-xs-24.col-sm-12.col-md-10 > div:nth-child(3) > div.detail-page-price.wt-detail-page-price > span > span",
            ".detail-page-price span",  # More general fallback
            ".wt-detail-page-price span",  # Alternative
            ".article-price__price"      # Another possible selector
        ]
        
        for selector in price_selectors:
            try:
                price_element = page.query_selector(selector)
                if price_element:
                    price = price_element.text_content().strip()
                    if price:
                        break
            except Exception:
                continue
        
        # Extract description
        description = extract_description(page)
        
        # Extract specifications
        specs = extract_specs(page)
        
        # Create watch data object
        watch_data = {
            "url": watch_url,
            "name": watch_name,
            "price": price,
            "description": description,
            "specifications": specs
        }
        
        print(f"Extracted: {watch_name} ({price})")
        return watch_data
    
    except Exception as e:
        print(f"Error processing watch detail page {watch_url}: {e}")
        return None

def process_listing_page(page: Page, page_url: str) -> List[str]:
    """Process a brand listing page and extract all watch URLs."""
    watch_urls = []
    
    try:
        # Navigate to the listing page
        page.goto(page_url)
        page.wait_for_load_state("networkidle", timeout=30000)
        
        # Wait for watch listings to appear
        page.wait_for_selector("#wt-watches", timeout=30000)
        
        # Extract all watch listing links
        n = 1
        while True:
            # Try to find the nth child
            selector = f"#wt-watches > div:nth-child({n}) > a"
            link = page.query_selector(selector)
            
            if not link:
                break  # No more children found
            
            href = link.get_attribute("href")
            if href and href not in watch_urls:
                # Make the URL absolute if needed
                if not href.startswith("http"):
                    href = f"https://www.chrono24.com{href}"
                watch_urls.append(href)
            
            n += 1
        
        print(f"Found {len(watch_urls)} watch listings on page {page_url}")
        return watch_urls
    
    except Exception as e:
        print(f"Error processing listing page {page_url}: {e}")
        return []

def process_brand(page: Page, brand: Dict) -> List[Dict]:
    """Process all pages for a brand and extract watch details."""
    all_watches = []
    all_watch_urls = set()  # Use a set to avoid duplicates
    
    try:
        brand_name = brand["name"]
        brand_base_url = brand["url"].replace("/index.htm", "")
        
        print(f"\nProcessing brand: {brand_name}")
        
        # Start with page 1
        page_index = 1
        has_more_pages = True
        
        while has_more_pages:
            page_url = f"{brand_base_url}/index-{page_index}.htm" if page_index > 1 else f"{brand_base_url}/index.htm"
            print(f"Processing page {page_index}: {page_url}")
            
            # Try to process the page with retries
            retry_count = 0
            watch_urls = []
            
            while retry_count < MAX_RETRIES:
                try:
                    watch_urls = process_listing_page(page, page_url)
                    break
                except Exception as e:
                    retry_count += 1
                    print(f"Retry {retry_count}/{MAX_RETRIES} for {page_url}: {e}")
                    if retry_count == MAX_RETRIES:
                        print(f"Failed to process {page_url} after {MAX_RETRIES} retries")
                    polite_delay()
            
            # Check if we found any new watches
            new_urls = [url for url in watch_urls if url not in all_watch_urls]
            
            if not new_urls:
                # No new watches found, we've reached the end of pagination
                print(f"No new watches found on page {page_index}, stopping pagination")
                has_more_pages = False
            else:
                # Add new URLs to our set
                all_watch_urls.update(new_urls)
                
                # Process each watch URL
                for watch_url in new_urls:
                    polite_delay()
                    retry_count = 0
                    
                    while retry_count < MAX_RETRIES:
                        try:
                            watch_data = process_watch_detail(page, watch_url)
                            if watch_data:
                                watch_data["brand"] = brand_name
                                all_watches.append(watch_data)
                                
                                # Save batch to avoid data loss in case of errors
                                if len(all_watches) % BATCH_SIZE == 0:
                                    print(f"Saving batch of {len(all_watches)} watches...")
                                    save_watches_to_json(all_watches)
                            
                            break  # Break retry loop if successful
                        except Exception as e:
                            retry_count += 1
                            print(f"Retry {retry_count}/{MAX_RETRIES} for {watch_url}: {e}")
                            if retry_count == MAX_RETRIES:
                                print(f"Failed to process {watch_url} after {MAX_RETRIES} retries")
                            polite_delay()
                
                # Move to next page
                page_index += 1
    
    except Exception as e:
        print(f"Error processing brand {brand['name']}: {e}")
    
    return all_watches

def main():
    """Main function to orchestrate the watch extraction process."""
    # Create data directory if needed
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Load brands
    brands = load_brands()
    if not brands:
        print("No brands found. Please run extract_brands.py first.")
        return
    
    print(f"Loaded {len(brands)} brands")
    
    # Initialize watches list
    all_watches = []
    
    # Launch Playwright browser
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,  # Set to True for production
            slow_mo=50  # Slow down actions for visibility during development
        )
        
        # Create a new browser context with a realistic viewport
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        
        # Create a new page
        page = context.new_page()
        
        try:
            # Process only a subset of brands for testing
            # Remove [:3] to process all brands
            for brand in brands[:3]:
                brand_watches = process_brand(page, brand)
                all_watches.extend(brand_watches)
                
                # Save after each brand to avoid data loss
                if brand_watches:
                    save_watches_to_json(all_watches)
            
            # Final save
            if all_watches:
                save_watches_to_json(all_watches)
                print(f"Extracted a total of {len(all_watches)} watches from {len(brands)} brands")
            else:
                print("No watches were extracted")
        
        except Exception as e:
            print(f"Error in main process: {e}")
            # Save whatever watches we've collected so far
            if all_watches:
                save_watches_to_json(all_watches)
        
        finally:
            # Clean up
            context.close()
            browser.close()

if __name__ == "__main__":
    main() 