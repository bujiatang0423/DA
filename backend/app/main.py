import uvicorn
from backend.app.bootstrap.application import build_application
from backend.app.bootstrap.settings import Settings

app = build_application()


def run() -> None:
    settings = Settings()
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
