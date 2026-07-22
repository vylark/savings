from fastapi import FastAPI

app = FastAPI(
    title="Savings and Investments API",
    description="Backend unified single-entry ledger platform tracking fractional physical/virtual savings.",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint to verify container and server operation."""
    return {"status": "healthy"}
