#!/usr/bin/env python3
import json
import os
from playwright.sync_api import sync_playwright

def extract_brands():
    """
    Extract brand names and URLs from the Chrono24 A-Z brand directory.
    
    Returns:
        List of dictionaries with brand name and URL
    """
    with sync_playwright() as pw:
        # Launch browser
        browser = pw.chromium.launch(headless=False)
        
        # Create context and page
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        
        try:
            # Navigate to the A-Z brand listing page
            print("Navigating to Chrono24 brands page...")
            page.goto("https://www.chrono24.com/search/browse.htm")
            
            # Wait for the brand list to load
            print("Waiting for brand links to load...")
            page.wait_for_selector("#main-content .letter-register section div nav ul li a")
            
            # Extract all brand links and their text
            print("Extracting brand data...")
            brand_data = page.eval_on_selector_all("#main-content .letter-register section div nav ul li a", """
                (elements) => elements.map(el => {
                    return {
                        name: el.textContent.trim(),
                        url: el.href
                    }
                })
            """)
            
            print(f"Found {len(brand_data)} brands")
            
            # Print first 5 brands for verification
            for i, brand in enumerate(brand_data[:5]):
                print(f"{i+1}. {brand['name']} - {brand['url']}")
            
            return brand_data
            
        finally:
            # Clean up
            context.close()
            browser.close()

def save_brands_to_json(brands, filename="./data/brands.json"):
    """Save brand data to a JSON file"""
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    # Write to JSON file
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(brands, f, indent=2, ensure_ascii=False)
    
    print(f"Brand data saved to {filename}")

if __name__ == "__main__":
    # Extract brands
    brands = extract_brands()
    
    # Save to JSON
    save_brands_to_json(brands) 