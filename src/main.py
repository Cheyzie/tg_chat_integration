import toml
import uvicorn
from contextlib import asynccontextmanager

from typing import Any
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.security import APIKeyHeader
from aiogram import Bot, Dispatcher, Router, types
from aiogram.enums.parse_mode import ParseMode
from aiogram.filters import CommandStart, Filter, Command
from aiogram.types import Message

class Chat(BaseModel):
    id: str

class Repl(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.reply_to_message is not None

config: dict = toml.load(Path(__file__).parent.with_name("config.toml"))
global_chat = {"id": config["telegram"]["chat_id"]}
ws_map: dict[str, dict[str, any]] = {}
opperators: dict[str, dict[str, any]] = {}
bot = Bot(
    token=config["telegram"]["bot_token"],
    parse_mode=ParseMode.HTML,
    disable_web_page_preview=True
)

dp = Dispatcher()
telegram_router = Router(name="telegram")
dp.include_router(telegram_router)


@telegram_router.message(CommandStart())
async def handle_start(message: Message):
    await message.answer(f'*Welcome to My Intergram* \nYour unique chat id is `{message.chat.id}`\nUse it to link between the embedded chat and this telegram chat', 'Markdown')

@telegram_router.message(Repl())
async def handle_text(message: Message):
    reply_text = message.reply_to_message.text
    if reply_text is None or reply_text == "":
        return
    name = reply_text.split(":")[0]
    if name in ws_map:
        await ws_map[name]["ws"].send_text(message.text)


@asynccontextmanager
async def lifespan(app: FastAPI):
    webhook_url = f"{config['webhook']['domain']}{config['webhook']['path']}"
    print(webhook_url)
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != webhook_url:
        await bot.set_webhook(
            url=webhook_url,
        )
    yield
    await bot.session.close()   

app = FastAPI(lifespan=lifespan)
header_scheme=APIKeyHeader(name="x-api-key")

@app.post(config["webhook"]["path"])
async def webhook(update: dict[str, Any]) -> None:
    await dp.feed_webhook_update(bot=bot, update=types.Update(**update))

@app.put("/telegram/chat")
def set_chat_id(chat: Chat, key = Depends(header_scheme)):
    if key != config["auth"]["api_key"]:
        raise HTTPException(status_code=403)
    global_chat["id"] = chat.id
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, name:str = 'Unknown', sessionID: str = ""):
    await websocket.accept()
    if sessionID == "": 
        await websocket.close(reason="sessionID is not specified")
        return
    name=f'{name}[{sessionID}]'
    ws_map[name] = {"ws": websocket, "name": name, "message_sent": False, "chatting": "Nobody"}
    try:
        while True:
            data = await websocket.receive_text()
            if data != "":
                ws_map[name]["message_sent"] = True
            await bot.send_message(global_chat["id"], f'{name}: {data}')
    except WebSocketDisconnect:
        if ws_map[name]["message_sent"]:
            await bot.send_message(global_chat["id"], f'{name} has disconnected')
        del ws_map[name]




if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, loop="uvloop")
