# FastAPI app entrypoint. Routers and startup-time catalog ingestion are wired here in a later phase.
from fastapi import FastAPI

app = FastAPI(title="Emporium Product Tool Service")
