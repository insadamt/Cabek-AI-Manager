"""Start the host-side Cabek manager; depends on Uvicorn and the local API factory."""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Cabek AI Manager — local installation and updates")
    parser.add_argument("--port", type=int, default=8179)
    arguments = parser.parse_args()
    uvicorn.run("manager.api:create_app", factory=True, host="127.0.0.1", port=arguments.port, access_log=False)


if __name__ == "__main__":
    main()
