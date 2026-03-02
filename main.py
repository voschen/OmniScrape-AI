# Can add agentic if its news -> RSS ; something else -> Jina.ai reader ; JS-heavy sites -> Playwright as last resort

import os
from ddgs import DDGS
import aiohttp
import asyncio
import bs4
import logging
from dotenv import load_dotenv
from pydantic import BaseModel, Field
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")



class ScrapedItem (BaseModel):
    Title: str
    Body: str
    Confidence: float = Field (
        ge = 0,
        le= 100
    )

def search_agent (query: str, num_results: int = 3):
    search_tool = DDGS()
    search_results = search_tool.text(query, safesearch = "moderate", max_results=num_results)

    url_list = []
    for result in search_results:
        url = result["href"]
        url_list.append(url)
    return url_list

async def navigator_agent (session, url):

    try:
        # Getting HTML
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        response = await session.get(url, headers = headers)

        if response.status != 200:
            logger.warning(f"Failed to fetch {url}: Status {response.status}")
            return ""
        
        html = await response.text() 

        # Parsing HTML
        soup = bs4.BeautifulSoup(html, 'lxml')

        noise_tags = soup.find_all(['script', 'style', 'nav', 'footer', 'header'])

        for tag in noise_tags:
            tag.decompose()

        text = soup.get_text(separator=' ', strip=True)
        return text[:12000]

    except Exception as e:
        logger.error(f"Error navigating {url}: {e}")
        return ""


async def extractor_agent(key, text, client):
    url = "https://openrouter.ai/api/v1/chat/completions  "
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/llama-3-8b-instruct",
        "messages": [
            {"role": "user", 
             "content": f"""You must respond with ONLY a valid JSON object containing exactly these three fields, nothing else:
            {{"Title": "page title here", "Body": "summary here", "Confidence": 85}}

            Rules:
            - Confidence MUST be a number (0-100), never omit it
            - No extra fields, no arrays, no nesting
            - No explanation, just the JSON

            Content to extract from: {text}"""
             }
             ],
        "response_format": {"type": "json_object"} 
    }

    async with client.post(url, headers=headers, json=payload) as response:
        data = await response.json()
    content = data['choices'][0]['message']['content']
    return ScrapedItem.model_validate_json(content)

async def answer_agent(key, information, client):
    url = "https://openrouter.ai/api/v1/chat/completions  "
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/llama-3-8b-instruct",
        "messages": [
            {"role": "user", 
             "content": f"""Go through all the information to you, and proceed to add an overarching answer to the provided question:
             question: {query}
             information: {information}
             """
             }
             ],
    }

    async with client.post(url, headers=headers, json=payload) as response:
        data = await response.json()
    content = data['choices'][0]['message']['content']
    return content

async def fetch_one_url(client, url):
    text = await navigator_agent(client, url)
    
    if not text:
        return None
    
    try:  
        extracted = await extractor_agent(API_KEY, text, client)
        return extracted
    except Exception as e:  
        logger.error(f"Extraction failed for {url}: {e}")
        return None  

async def main():                                 
    tasks = []

    timeout = aiohttp.ClientTimeout(total=10)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as client:
        
        urls = search_agent(query, 40)

        for url in urls:

            task = asyncio.create_task(fetch_one_url(client, url))
            tasks.append(task)

        results = await asyncio.gather(*tasks)
        valid_results = [r for r in results if r is not None]
        print("there are ", len(valid_results), "valid results!")
        answer = await answer_agent(API_KEY, valid_results, client)

    print(answer)


query = input(str("What is your prompt?"))
asyncio.run(main())