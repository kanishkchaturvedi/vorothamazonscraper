from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, ProxyConfig
import json
import asyncio
import os
from dotenv import load_dotenv
import google.generativeai as genai
import random
import string
import requests
import uuid

def generate_session_id():
    return f"SESSION_{uuid.uuid4().hex[:8].upper()}"

def rotate_session(api_key, session_id, product_type):
    url = "https://api.evomi.com/public/rotate_session"
    headers = {"x-apikey": api_key}
    params = {
        "sessionid": session_id,
        "product": product_type
    }
    
    response = requests.get(url, headers=headers, params=params)

# Load environment variables
load_dotenv()

Evomi_api_key = os.getenv('EVOMI_API_KEY')
if not Evomi_api_key:
    raise ValueError("EVOMI_API_KEY environment variable is not set")

# Set API Key from environment variable
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set")

genai.configure(api_key=api_key)

# Create a model instance
gemini_model = genai.GenerativeModel("gemini-1.5-pro")

def check_title_category_match(title: str, expected_category: str) -> bool:
    prompt = (
        f"Given the product title:\n\"{title}\"\n"
        f"Does this product title refer to a product in the category '{expected_category}'?\n"
        f"Important rules:\n"
        f"1. Exclude accessories, parts, covers, or any add-on items\n"
        f"2. Only include actual products in the category\n"
        f"3. For example:\n"
        f"   - For 'Washing Machine': exclude covers, lids, parts, or accessories\n"
        f"   - For 'Air Conditioner': exclude covers, stands, or installation parts\n"
        f"   - For 'Refrigerator': exclude covers, shelves, or replacement parts\n"
        f"   - For 'Television': exclude stands, mounts, or remote covers\n"
        f"4. If the product is an accessory or part, answer 'no'\n"
        f"5. If unsure, answer 'no'\n"
        f"\n"
        f"Answer only 'yes' or 'no' without any explanation."
    )

    try:
        response = gemini_model.generate_content(prompt)
        result = response.text.strip().lower()
        print(f"Gemini category match response: {result}")
        return "yes" in result
    except Exception as e:
        print(f"Error during Gemini classification: {e}")
        return False

def format_factor(product_category, factor, FACTOR_LABELS):
    if product_category == "Mobiles & Tablets":
        try:
            ram, storage = factor.split(',')
            return f"{ram}GB RAM {storage}GB Storage"
        except ValueError:
            return factor  # fallback if unexpected format
    else:
        unit = FACTOR_LABELS.get(product_category, "")
        return f"{factor} {unit}".strip()


async def extract_amazon_products(product_category, model_number, brand, factor):
    FACTOR_LABELS = {
        "Home Audio": "",
        "Television": "inch",
        "Mobiles & Tablets": "RAM and Storage",  # Still used for reference
        "Fans": "MM",
        "Coolers": "L",
        "Mixer Grinders": "Watt",
        "Water Purifiers": "L",
        "Vacuum Cleaners": "Watts",
        "Air Fryers": "Watts",
        "Geysers": "L",
        "Irons": "Watt",
        "Kettles": "L",
        "Sandwich Makers": "Watt",
        "Dishwashers": "L",
        "Air Conditioners": "Tonnage",
        "Microwave Ovens": "L",
        "Refrigerators": "L",
        "Washing Machine": "Kg",
        "Chimneys": "m3/hr",
    }

    proxy_config_evomi = ProxyConfig(
        server="http://premium-residential.evomi.com:1000",
        username="kanishkcha5",
        password="vdYFqTHTs8nCeYHqLEKY",
    )

    session_id = generate_session_id()
    rotate_session(api_key, session_id, "rpc")

    browswer_config = BrowserConfig(proxy_config=proxy_config_evomi)

    # Build query for main product
    factor_with_unit = format_factor(product_category, factor, FACTOR_LABELS)
    main_query = f"{brand} {factor_with_unit} {product_category} {model_number}".replace(' ', '+')
    main_url = f"https://www.amazon.in/s?k={main_query}"

    # Build query for competitors
    competitor_query = f"{factor_with_unit} {product_category}".replace(' ', '+')
    competitor_url = f"https://www.amazon.in/s?k={competitor_query}"

    crawler_config = CrawlerRunConfig(
        extraction_strategy=JsonCssExtractionStrategy(
            schema={
                "name": "Amazon product search result",
                "baseSelector": "[data-component-type='s-search-result']",
                "fields": [
                    {"name": "title", "selector": "h2 span", "type": "text"},
                    {"name": "reviews_count", "selector": ".a-size-base", "type": "text"},
                    {"name": "rating", "selector": ".a-icon-star-small .a-icon-alt", "type": "text"},
                    {"name": "price", "selector": ".a-price .a-offscreen", "type": "text"},
                    {"name": "url", "selector": ".a-link-normal", "type": "attribute", "attribute": "href"}
                ]
            }
        )
    )

    try:
        print(f"Starting extraction for: {brand} {factor} {product_category} {model_number}")
        async with AsyncWebCrawler(config=browswer_config) as crawler:
            # Get main product results
            main_result = await crawler.arun(url=main_url, config=crawler_config, cache_mode=CacheMode.BYPASS)
            main_products = json.loads(main_result.extracted_content) if main_result and main_result.extracted_content else []

            # Get competitor results
            competitor_result = await crawler.arun(url=competitor_url, config=crawler_config, cache_mode=CacheMode.BYPASS)
            competitor_products = json.loads(competitor_result.extracted_content) if competitor_result and competitor_result.extracted_content else []

            return main_products, competitor_products
    except Exception as e:
        print(f"Error during extraction: {e}")
        return [], []



def classify_products(main_products, competitor_products, model_number, brand_name, product_category=None, factor=None):
    main_product = None
    competitors = []

    FACTOR_LABELS = {
        "Home Audio": "",
        "Television": "inch",
        "Mobiles & Tablets": "RAM and Storage",
        "Fans": "MM",
        "Coolers": "L",
        "Mixer Grinders": "Watt",
        "Water Purifiers": "L",
        "Vacuum Cleaners": "Watts",
        "Air Fryers": "Watts",
        "Geysers": "L",
        "Irons": "Watt",
        "Kettles": "L",
        "Sandwich Makers": "Watt",
        "Dishwashers": "L",
        "Air Conditioners": "Tonnage",
        "Microwave Ovens": "L",
        "Refrigerators": "L",
        "Washing Machine": "Kg",
        "Chimneys": "m3/hr",
    }

    def title_has_factor(title: str, factor: str, unit: str) -> bool:
        title = title.lower()
        factor = str(factor).lower()
        return factor in title or (f"{factor} {unit}".lower() in title)

    unit = FACTOR_LABELS.get(product_category, "")
    factor_clean = factor.lower() if factor else ""

    # Find main product from main_products
    for product in main_products:
        title = product.get('title', '').lower()
        if model_number.lower() in title:
            if product_category and not check_title_category_match(title, product_category):
                continue
            main_product = product
            main_product['url'] = f"https://www.amazon.in{product.get('url')}"
            break

    # If we found a main product, use its title for type matching
    main_product_title = main_product.get('title', '') if main_product else None

    # Find competitors from competitor_products
    for product in competitor_products:
        title = product.get('title', '').lower()

        if brand_name.lower() in title:
            continue
        if product_category and not check_title_category_match(title, product_category):
            continue
        if factor and not title_has_factor(title, factor_clean, unit):
            continue
        # Add new check for product type matching
        if main_product_title and not check_product_type_match(title, main_product_title):
            continue

        important_fields = ['title', 'price', 'rating', 'reviews_count', 'url']
        if any(product.get(field) is None for field in important_fields):
            continue

        product['url'] = f"https://www.amazon.in{product.get('url')}"
        competitors.append(product)

        if len(competitors) == 5:
            break

    # Fallback: If main product was not found, search using Perplexity
    if main_product is None:
        print(f"Main product not found in search results. Searching with Perplexity for: {brand_name} {model_number}")
        main_product = search_product_with_perplexity(brand_name, model_number, product_category, factor)

    return main_product, competitors

def check_product_type_match(title: str, main_product_title: str) -> bool:
    prompt = (
        f"Given two product titles:\n"
        f"1. Main product: \"{main_product_title}\"\n"
        f"2. Potential competitor: \"{title}\"\n"
        f"Are these products of the same type/subtype? Consider these rules:\n"
        f"- For washing machines:\n"
        f"  * Semi-automatic should ONLY match with semi-automatic\n"
        f"  * Fully automatic should ONLY match with fully automatic\n"
        f"  * Front load should ONLY match with front load\n"
        f"  * Top load should ONLY match with top load\n"
        f"- For ACs:\n"
        f"  * Window AC should ONLY match with window AC\n"
        f"  * Split AC should ONLY match with split AC\n"
        f"- For vacuum cleaners:\n"
        f"  * Cordless should ONLY match with cordless\n"
        f"  * Robotic should ONLY match with robotic\n"
        f"  * Bagged should ONLY match with bagged\n"
        f"  * Bagless should ONLY match with bagless\n"
        f"- For refrigerators:\n"
        f"  * Single door should ONLY match with single door\n"
        f"  * Double door should ONLY match with double door\n"
        f"  * Side by side should ONLY match with side by side\n"
        f"\n"
        f"Important rules:\n"
        f"1. Different types should not match (e.g., semi-automatic should not match with fully automatic)\n"
        f"2. If the main product has multiple type indicators (e.g., 'semi-automatic top load'), both must match\n"
        f"3. If unsure, answer 'no'\n"
        f"\n"
        f"Answer only 'yes' or 'no' without any explanation."
    )

    try:
        response = gemini_model.generate_content(prompt)
        result = response.text.strip().lower()
        print(f"Gemini type match response: {result}")
        return "yes" in result
    except Exception as e:
        print(f"Error during Gemini type matching: {e}")
        return False

def search_product_with_perplexity(brand_name, model_number, product_category, factor):
    """
    Search for product information using Perplexity when the product is not found in Amazon search results.
    Returns product information in the same format as the scraper.
    """
    FACTOR_LABELS = {
        "Home Audio": "",
        "Television": "inch",
        "Mobiles & Tablets": "RAM and Storage",
        "Fans": "MM",
        "Coolers": "L",
        "Mixer Grinders": "Watt",
        "Water Purifiers": "L",
        "Vacuum Cleaners": "Watts",
        "Air Fryers": "Watts",
        "Geysers": "L",
        "Irons": "Watt",
        "Kettles": "L",
        "Sandwich Makers": "Watt",
        "Dishwashers": "L",
        "Air Conditioners": "Tonnage",
        "Microwave Ovens": "L",
        "Refrigerators": "L",
        "Washing Machine": "Kg",
        "Chimneys": "m3/hr",
    }

    factor_with_unit = format_factor(product_category, factor, FACTOR_LABELS)

    print(f"{brand_name} {model_number} {factor_with_unit} {product_category}")
    
    prompt = (
        f"Search the web for the current price, ratings and reviews for {brand_name} {model_number} {factor_with_unit} {product_category}. "
        f"Find the actual current information and return it in this exact JSON format:\n"
        f"{{\n"
        f"  \"reviews_count\": \"[actual number of reviews]\",\n"
        f"  \"rating\": \"[actual rating out of 5 stars]\",\n"
        f"  \"price\": \"[actual current price in INR]\"\n"
        f"}}\n\n"
        f"Important: Search for the real current data, not example data. If not found, return null for all fields."
    )

    try:
        # Perplexity API endpoint
        url = "https://api.perplexity.ai/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {os.getenv('PERPLEXITY_API_KEY')}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "llama-3.1-sonar-small-128k-online",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 150
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        result_text = response.json()["choices"][0]["message"]["content"].strip()
        
        print(f"Perplexity raw response: {result_text}")
        
        # Handle responses wrapped in markdown code blocks
        if result_text.startswith('```json'):
            # Remove the markdown code block wrapper
            result_text = result_text.replace('```json', '').replace('```', '').strip()
        elif result_text.startswith('```'):
            # Remove generic markdown code block wrapper
            result_text = result_text.replace('```', '').strip()
        
        # Try to extract JSON from the response - look for the first complete JSON object
        json_start = result_text.find('{')
        json_end = result_text.rfind('}')
        
        if json_start != -1 and json_end != -1 and json_end > json_start:
            # Extract just the JSON part
            json_text = result_text[json_start:json_end + 1]
            try:
                product_data = json.loads(json_text)
                
                # Construct the complete product data with title and URL
                complete_product_data = {
                    "title": f"{brand_name} {model_number}",
                    "price": product_data.get('price') or "",
                    "rating": normalize_rating_format(product_data.get('rating') or ""),
                    "reviews_count": product_data.get('reviews_count') or "",
                    "url": ""  # Keep URL blank as requested
                }
                
                # Convert "null" strings to blank strings
                for key in ['price', 'rating', 'reviews_count']:
                    if complete_product_data[key] == "null":
                        complete_product_data[key] = ""
                
                # Check if we got any meaningful data (not all null/empty)
                has_data = any(product_data.get(field) and product_data.get(field) != "null" for field in ['price', 'rating', 'reviews_count'])
                
                if has_data:
                    print(f"Found product via Perplexity: {complete_product_data.get('title', 'Unknown')}")
                    return complete_product_data
                else:
                    print("No product data found via Perplexity")
                    return None
            except json.JSONDecodeError as e:
                print(f"Error parsing extracted JSON: {e}")
                return None
        else:
            print("No valid JSON object found in Perplexity response")
            return None
            
    except json.JSONDecodeError as e:
        print(f"Error parsing Perplexity JSON response: {e}")
        return None
    except Exception as e:
        print(f"Error during Perplexity product search: {e}")
        return None

def normalize_rating_format(rating):
    """
    Normalize rating format to 'xx out of 5 stars' format.
    Handles various input formats like '4.5/5', '4.5/5 stars', '4.5 out of 5', etc.
    Returns blank if the rating is descriptive text instead of a number.
    """
    if not rating:
        return ""
    
    rating = str(rating).strip()
    
    # If rating contains descriptive text instead of numbers, return blank
    descriptive_phrases = [
        "not explicitly provided",
        "not available",
        "not found",
        "generally rated well",
        "based on the context",
        "no rating",
        "unavailable"
    ]
    
    rating_lower = rating.lower()
    for phrase in descriptive_phrases:
        if phrase in rating_lower:
            return ""
    
    # Handle "xx/5 stars" format
    if "/5" in rating:
        # Extract the number before "/5"
        parts = rating.split("/5")
        if parts and parts[0]:
            try:
                rating_value = parts[0].strip()
                return f"{rating_value} out of 5 stars"
            except:
                pass
    
    # Handle "xx out of 5" format (already correct)
    if "out of 5" in rating:
        if "stars" not in rating:
            return f"{rating} stars"
        return rating
    
    # Handle just numbers (assume out of 5)
    try:
        rating_value = float(rating)
        if 0 <= rating_value <= 5:
            return f"{rating_value} out of 5 stars"
    except:
        pass
    
    # If no pattern matches and it's not a number, return blank
    return ""
