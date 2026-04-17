from assistant.app import app
import uvicorn
import argparse
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8001, help='服务端口')
    args = parser.parse_args()
    
    uvicorn.run("assistant.app:app", host="0.0.0.0", port=args.port, reload=False)
