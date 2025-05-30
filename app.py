from fastapi import FastAPI, Query, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
import asyncio
from anyio.to_thread import run_sync
from amazon_scraper import extract_amazon_products, classify_products
import uvicorn

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.get("/search")
async def search(
    product_category: str,
    model_number: str,
    brand: str,
    factor: str,
    background_tasks: BackgroundTasks
):
    try:
        # Pass all 4 inputs to the extraction function
        main_products, competitor_products = await run_sync(lambda: asyncio.run(
            extract_amazon_products(product_category, model_number, brand, factor)
        ))
        main_product, competitors = classify_products(
            main_products=main_products,
            competitor_products=competitor_products,
            model_number=model_number,
            brand_name=brand,
            product_category=product_category,
            factor=factor
        )
        background_tasks.add_task(restart_server)

        return {
            "main_product": main_product,
            "competitors": competitors
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/bulk_search")
async def bulk_search(products: List[Dict[str, str]], background_tasks: BackgroundTasks):
    results = []

    # Tasks to search for each product in the bulk request
    tasks = [
        search_product_on_amazon(
            product_category=p["product_category"], 
            model_number=p["model_number"], 
            brand=p["brand"],
            factor=p["factor"],
            background_tasks=background_tasks
        )
        for p in products
    ]

    # Run the tasks concurrently
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    # Process the responses
    for i, response in enumerate(responses):
        product_data = products[i]
        if isinstance(response, Exception):
            results.append({
                "product_category": product_data["product_category"],
                "error": str(response)
            })
        else:
            product_info, competitors = response
            results.append({
                "product_category": product_data["product_category"],
                "product_info": product_info,
                "competitors": competitors
            })

    return {"results": results}

async def search_product_on_amazon(
    product_category: str, 
    model_number: str, 
    brand: str, 
    factor: str,
    background_tasks: BackgroundTasks
):
    try:
        # Run extract_amazon_products in a fresh asyncio loop inside a separate thread
        main_products, competitor_products = await run_sync(lambda: asyncio.run(
            extract_amazon_products(product_category, model_number, brand, factor)
        ))

        main_product, competitors = classify_products(
            main_products=main_products,
            competitor_products=competitor_products,
            model_number=model_number,
            brand_name=brand,
            product_category=product_category,
            factor=factor
        )

        # Add the restart task to the background, so it happens after the response is sent
        background_tasks.add_task(restart_server)

        return main_product, competitors
    except Exception as e:
        return e

def restart_server():
    """Function to restart the FastAPI server"""
    import os
    import sys
    print("Restarting server...")
    os.execv(sys.executable, ['python'] + sys.argv)



if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)