from fastapi import FastAPI, Query, Body, BackgroundTasks
from typing import List, Dict
import asyncio
from anyio.to_thread import run_sync
from amazon_scraper import extract_amazon_products, classify_products
import uvicorn

app = FastAPI()

@app.get("/search")
async def search(product_name: str, model_number: str, brand: str, background_tasks: BackgroundTasks):
    try:
        # Run extract_amazon_products in a fresh asyncio loop inside a separate thread
        products = await run_sync(lambda: asyncio.run(extract_amazon_products(product_name)))

        main_product, competitors = classify_products(products, model_number, brand)

        # Add the restart task to the background, so it happens after the response is sent
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
        search_product_on_amazon(p["product_name"], p["model_number"], p["brand"], background_tasks)
        for p in products
    ]

    # Run the tasks concurrently
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    # Process the responses
    for i, response in enumerate(responses):
        product_data = products[i]
        if isinstance(response, Exception):
            results.append({
                "product_name": product_data["product_name"],
                "error": str(response)
            })
        else:
            product_info, competitors = response
            results.append({
                "product_name": product_data["product_name"],
                "product_info": product_info,
                "competitors": competitors
            })

    return {"results": results}

async def search_product_on_amazon(product_name: str, model_number: str, brand: str, background_tasks: BackgroundTasks):
    try:
        # Run extract_amazon_products in a fresh asyncio loop inside a separate thread
        products = await run_sync(lambda: asyncio.run(extract_amazon_products(product_name)))

        main_product, competitors = classify_products(products, model_number, brand)

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