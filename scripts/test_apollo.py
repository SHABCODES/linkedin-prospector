import asyncio
import os
import sys

from app.config import get_settings
from app.services.discovery import discover_prospects
from app.services.enricher import enrich_profile

async def main():
    settings = get_settings()
    
    if not settings.apollo_api_key:
        print("❌ Error: APOLLO_API_KEY is not set in your .env file.")
        print("Please add it before running this test script.")
        sys.exit(1)
        
    print(f"✅ Apollo API Key found: {settings.apollo_api_key[:4]}...{settings.apollo_api_key[-4:]}")
    print("\n🔍 Running live search for: 'VP Sales at SaaS'")
    
    try:
        raw_profiles = await discover_prospects(query="VP Sales at SaaS", max_results=2)
        print(f"\n✅ Successfully fetched {len(raw_profiles)} profiles from Apollo.io!")
        
        if not raw_profiles:
            print("⚠️ No profiles found. Try a broader search query.")
            return

        for idx, raw in enumerate(raw_profiles):
            print(f"\n--- 👤 Profile {idx + 1} ---")
            enriched = await enrich_profile(raw)
            print(f"Name:       {enriched.get('full_name')}")
            print(f"Title:      {enriched.get('current_title')}")
            print(f"Company:    {enriched.get('current_company')}")
            print(f"Location:   {enriched.get('location')}")
            print(f"Industry:   {enriched.get('industry')}")
            
    except Exception as e:
        print(f"\n❌ Error during Apollo API call: {e}")

if __name__ == "__main__":
    asyncio.run(main())
