from fastapi import FastAPI

app = FastAPI(
    title="Savings and Investments API",
    description="Backend double-entry ledger platform tracking fractional physical/virtual savings.",
    version="0.1.1",
)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint to verify container and server operation."""
    return {"status": "healthy"}
