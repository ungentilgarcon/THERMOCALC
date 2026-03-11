import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import SESSION_SECRET
from app.services.admin_state import load_admin_state
from app.services.runtime_measurements import stop_runtime_subscriptions, sync_runtime_subscriptions
from app.services.scheduler import scheduler_loop


@asynccontextmanager
async def lifespan(_: FastAPI):
	sync_runtime_subscriptions(load_admin_state())
	task = asyncio.create_task(scheduler_loop())
	try:
		yield
	finally:
		stop_runtime_subscriptions()
		task.cancel()
		with suppress(asyncio.CancelledError):
			await task


app = FastAPI(title="ThermoCalc", version="0.1.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
