"""
Requiem Demo Shop
FastAPI app with Flagsmith remote evaluation and OTel tracing
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import random
import time
import logging

# Note: In real app, would use flagsmith SDK + OTel
# For spike, we simulate the core flow

app = FastAPI(title="Requiem Demo Shop")
logger = logging.getLogger(__name__)

# Simulated feature flags (in real app, calls Flagsmith get_experiment_flag)
FLAGS = {
    "new_checkout": "control",  # Will be "treatment" for some users
    "buy_button": "control",    # Will be "treatment" for some users
}

@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy"}

@app.post("/track/exposure")
async def track_exposure(identifier: str, flag_key: str, variant: str):
    """
    Simulate SDK exposure event (flag_exposure)
    In real app: Flagsmith SDK auto-tracks this via get_experiment_flag()
    """
    logger.info(f"Exposure: {identifier} -> {flag_key}={variant}")
    return {"recorded": True}

@app.post("/track/event")
async def track_event(identifier: str, event_name: str, value: float = 1.0):
    """
    Simulate SDK event tracking (purchase, error, etc.)
    In real app: Flagsmith SDK auto-tracks via track_event()
    """
    logger.info(f"Event: {identifier} -> {event_name}={value}")
    return {"recorded": True}

@app.get("/product/{product_id}")
async def get_product(product_id: str, user_id: str):
    """
    GET /product/123?user_id=user_42
    
    Returns product info. Variant depends on flag.
    In real app: calls get_experiment_flag("buy_button", identifier=user_id)
    """
    
    # Simulate flag evaluation
    variant = random.choice(["control", "treatment"])  # Real app: Flagsmith
    
    # Simulate OTel span tags (would be real OTel in production)
    tags = {
        "flag.key": "buy_button",
        "flag.variant": variant,
    }
    
    # Different product UX per variant
    if variant == "control":
        button_text = "Buy Now"
        button_color = "blue"
    else:
        button_text = "Complete Purchase"
        button_color = "green"
    
    return {
        "product_id": product_id,
        "name": "Demo Product",
        "price": 99.99,
        "button": {
            "text": button_text,
            "color": button_color,
        },
        "variant": variant,
        "tags": tags,
    }

@app.post("/checkout")
async def checkout(user_id: str, amount: float):
    """
    POST /checkout with user_id and amount
    
    Demonstrates the new_checkout flag:
    - control: works fine (200 OK)
    - treatment: simulates potential error (see fault_injection)
    """
    
    # Simulate flag evaluation
    variant = random.choice(["control", "treatment"])
    
    # Simulate OTel span
    start = time.time()
    
    try:
        # Control: fast checkout
        if variant == "control":
            time.sleep(random.uniform(0.1, 0.3))  # 100-300ms
            status = 200
            message = "Order placed"
        else:
            # Treatment: might be slow or error (simulates new feature under test)
            time.sleep(random.uniform(0.5, 2.0))  # 500-2000ms (slow!)
            if random.random() < 0.1:  # 10% error rate
                raise HTTPException(status_code=500, detail="Checkout service error")
            message = "Order placed (new flow)"
            status = 200
        
        duration_ms = (time.time() - start) * 1000
        
        # Record OTel metrics (in real app: auto-instrumented)
        return {
            "status": "success",
            "order_id": f"ORD_{user_id}_{int(time.time())}",
            "variant": variant,
            "amount": amount,
            "duration_ms": duration_ms,
            "message": message,
        }
    except HTTPException as e:
        raise

@app.post("/feature-health/webhook")
async def feature_health_webhook(data: dict):
    """
    Feature Health webhook from Requiem/Grafana
    
    Payload:
    {
        "feature": "new_checkout",
        "environment": "production",
        "status": "unhealthy",
        "reason": "Error rate 15% > 2% threshold"
    }
    """
    logger.warning(f"Feature health alert: {data}")
    return {"acknowledged": True}

@app.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint
    In real app: prometheus_client library exports this
    """
    # Simulated metrics
    return {
        "error_rate": {
            "control": 0.01,
            "treatment": 0.15,  # High error rate on treatment
        },
        "p95_ms": {
            "control": 300,
            "treatment": 1500,  # Slow on treatment
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
