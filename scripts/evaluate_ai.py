import asyncio
import json
import logging
from pathlib import Path

from app.services.qualifier import qualify_prospect
from app.config import get_settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("evaluate_ai")

# Mock labeled dataset for evaluation
LABELED_DATA = [
    {
        "prospect": {
            "full_name": "Arjun Sharma",
            "headline": "VP Sales @ Groww | Ex-Razorpay | B2B SaaS | Fintech",
            "current_title": "VP Sales",
            "current_company": "Groww",
            "location": "Bengaluru, Karnataka, India",
            "industry": "Financial Services",
            "tenure_months": 24,
            "role_change_detected": False,
            "recent_post_snippet": "Why most SaaS SDR teams are set up to fail",
            "education": [{"school": "IIM Bangalore"}]
        },
        "expected_classification": "High Fit"
    },
    {
        "prospect": {
            "full_name": "Priya Menon",
            "headline": "Director of GTM | Series B SaaS | PLG → Enterprise Motion",
            "current_title": "Director of GTM",
            "current_company": "Saaslabs",
            "location": "Bengaluru, Karnataka, India",
            "industry": "Software Development",
            "tenure_months": 12,
            "role_change_detected": True,
            "recent_post_snippet": "We just crossed ₹10Cr ARR",
            "education": [{"school": "BITS Pilani"}]
        },
        "expected_classification": "High Fit"
    },
    {
        "prospect": {
            "full_name": "Unknown Person",
            "headline": "Student at University",
            "current_title": "Student",
            "current_company": "University",
            "location": "Remote",
            "industry": "Higher Education",
            "tenure_months": 0,
            "role_change_detected": False,
            "recent_post_snippet": None,
            "education": []
        },
        "expected_classification": "Reject"
    }
]

async def run_evaluation():
    settings = get_settings()
    if not settings.llm_enabled:
        log.warning("LLM is not enabled. Evaluation will only test deterministic scoring.")

    correct = 0
    total = len(LABELED_DATA)
    
    log.info(f"Starting evaluation on {total} prospects...")
    
    for i, item in enumerate(LABELED_DATA):
        prospect = item["prospect"]
        expected = item["expected_classification"]
        
        result = await qualify_prospect(prospect)
        actual = result["classification"]
        
        log.info(f"[{i+1}/{total}] {prospect['full_name']}")
        log.info(f"  Expected: {expected} | Actual: {actual} (Score: {result['score']})")
        log.info(f"  Reasons: {result.get('reasons')}")
        log.info(f"  Risks: {result.get('risks')}")
        
        if expected == actual:
            correct += 1
            
    accuracy = (correct / total) * 100
    log.info(f"Evaluation Complete. Accuracy: {accuracy:.2f}% ({correct}/{total})")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
