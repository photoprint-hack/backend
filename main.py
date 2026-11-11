import uvicorn


def main() -> None:
    """Run the development server (see README for alternatives)."""
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
