#!/usr/bin/env python3

import asyncio
import aioredis
import uvicorn
import hashlib
import mimetypes
import random
import string
from typing import Optional
from fastapi import FastAPI, WebSocket, Response, HTTPException, File, UploadFile, Depends, Response

from config import *
from security import token_to_user, router as security_router

app = FastAPI()
app.include_router(security_router)


@app.post('/alloc')
async def alloc(user: str = Depends(token_to_user)):
    # Create a random URL
    url = ''.join(random.choice(string.ascii_letters) for _ in range(URL_SIZE))

    # Add the user to it
    r = await open_redis()
    await r.hset('url' + url, 'user', user)

    return {'url': url}


@app.put('/{url}')
async def put(
        url: str,
        user: str = Depends(token_to_user),
        data: UploadFile = File(...)):

    # Connect to the database
    r = await open_redis()

    # Make sure the URL is assigned to the user
    owner = await r.hget('url' + url, 'user')
    if not owner or user != owner.decode():
        raise HTTPException(status_code=403, detail=f"{user} doesn't have permission to write to {url}")

    # Set the data
    media_type = mimetypes.guess_type(data.filename)[0]
    if not media_type:
        media_type = "application/octet-stream"
    await r.hset('url' + url, 'media_type', media_type)
    datab = await data.read()
    await r.hset('url' + url, 'data', datab)

    return "Success"


@app.get('/{url}')
async def get(url: str):

    # Connect to the database
    r = await open_redis()

    # Check if the URL exists
    if not await r.hexists(url, 'data'):
        raise HTTPException(status_code=404, detail="Not Found")

    # Fetch the data
    datab      = await r.hget('url' + url, 'data')
    media_type = (await r.hget('url' + url, 'media_type')).decode()

    return Response(datab, media_type=media_type)


@app.delete('/{url}')
async def delete(url: str, user = Depends(token_to_user)):

    # Connect to the database
    r = await open_redis()

    # Make sure it is owned by the user
    owner = await r.hget('url' + url, 'user')
    if not owner or user != owner.decode():
        raise HTTPException(status_code=403, detail=f"{user} doesn't have permission to delete {url}")

    # Delete the data and mimetype (keep ownership)
    await r.hdel('url' + url, 'data', 'mimetype')

    return "Success"


def key_url_to_uuid(key: str, url: str):
    # Concatenate the hashes of the key and url
    # This prevents trickiness where
    # key+url is ambiguous
    key_hash = hashlib.sha256(key.encode()).digest()
    url_hash = hashlib.sha256(url.encode()).digest()
    return key_hash + url_hash


@app.post('/perform')
async def perform(
        key: str, url: str,
        user = Depends(token_to_user)):

    # Get a unique performer id that
    # describes the key/url pair
    per = key_url_to_uuid(key, url)

    # Connect to the database and lock
    r = await open_redis()
    lock = r.lock(b'loc' + per)
    await lock.acquire()

    # If the performance is new
    if await r.scard(b'per' + per) == 0:
        # Add it to the stream
        xid = await r.xadd('key' + key, {'url': url})
        # Map the id to its stream id
        # so it can be deleted.
        await r.hset(b'xid' + per, 'xid', xid)

    # Add the member to the set
    await r.sadd(b'per' + per, user)

    # Release
    await lock.release()
    return "Success"


@app.post('/retire')
async def retire(
        key: str, url: str,
        user = Depends(token_to_user)):

    # Get a unique performer id that
    # describes the key/url pair
    per = key_url_to_uuid(key, url)

    # Connect to the database and lock
    r = await open_redis()
    lock = r.lock(b'loc' + per)
    await lock.acquire()

    # Remove the user from the performance
    await r.srem(b'per' + per, user)

    # If no one is performing,
    # remove the performance from the stream
    if await r.scard(b'per' + per) == 0:
        # Get the stream ID of the pair
        xid = await r.hget(b'xid' + per, 'xid')
        if xid:
            # Remove it from the stream
            await r.xdel('key' + key, xid)
            await r.hdel(b'xid' + per, 'xid')

    # Release
    await lock.release()
    return "Success"


@app.websocket("/")
async def attend(ws:  WebSocket):

    # Open the websocket connection
    await ws.accept()
    r = await open_redis()

    # Initialize list to attend to
    attending = []

    # Fetch ancient children
    latest_id = '0'
    events = None

    while True:
        # Initialize a JSON object

        # If there are events, send them
        if events:
            for key, e_id, url in events:
                latest_id = e_id

                try:
                    await ws.send_text(str(child))
                except:
                    break

        try:
            await ws.send_text(str(child))
        except:
            break

        # Wait for a list of new streams to add or delete, which could be none.
        message = await asyncio.wait_for(ws.receive_text(), PONG_INTERVAL)
        # Add or delete them from the list
        attending += message

        # Wait for new events
        events = await r.xread(attending,
                               latest_ids=[latest_id],
                               timeout=CHILDREN_INTERVAL)


# Open and close a redis connection
async def open_redis():
    return await aioredis.from_url("redis://redis")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
