import uvicorn
from backend.app.bootstrap.application import build_application
from backend.app.bootstrap.settings import Settings
from backend.app.infrastructure.logging import configure_request_logging

app = build_application()


def run() -> None:
    settings = Settings()
    configure_request_logging()
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port, access_log=False)


if __name__ == "__main__":
    run()
