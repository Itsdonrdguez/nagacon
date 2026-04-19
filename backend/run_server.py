import uvicorn


if __name__ == "__main__":
    print("Starting server...")
    # On Windows, reload mode should use an import string under a __main__ guard.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
