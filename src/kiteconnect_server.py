from fastapi import FastAPI, Request
import uvicorn

app = FastAPI(title="Kite Connect Auth Callback Server")

@app.get("/")
async def root():
    return {"message": "Kite Connect Callback Server Running"}

@app.get("/callback")
async def callback(request: Request):
    params = dict(request.query_params)
    print("\n" + "="*50)
    print("ZERODHA KITE CONNECT CALLBACK RECEIVED:")
    print(params)
    print("="*50 + "\n")
    return {
        "status": "success",
        "message": "Login successful! Check server logs for request_token.",
        "params": params
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
