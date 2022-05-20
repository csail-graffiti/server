import json
import asyncio
from uuid import uuid4
from aio_pika import Message
from contextlib import asynccontextmanager

from .rewrite import query_rewrite

class PubSub:

    def __init__(self, db, mq):
        self.db = db

        self.sockets = {} # socket_id -> socket
        self.socket_to_queries = {} # socket_id -> set of query hashes
        self.query_to_sockets  = {} # query_hash -> set of socket ids

        self.initialized = asyncio.Event()
        asyncio.create_task(self.initialize(mq))

    async def initialize(self, mq):
        # Create queues to send subscription requests
        # and then retrieve results from the broker
        self.channel = await mq.channel()
        self.request_queue = await self.channel.declare_queue(
                'subscription_requests')
        self.result_queue  = await self.channel.declare_queue(
                'subscription_results')

        # Start listening to results
        await self.result_queue.consume(self.on_results, no_ack=True)

        self.initialized.set()

    @asynccontextmanager
    async def register(self, ws):
        # Allocate space for this socket's subscriptions
        socket_id = str(uuid4())
        self.sockets[socket_id] = ws
        self.socket_to_queries[socket_id] = set()

        try:
            yield socket_id

        finally:
            # Unsubscribe the socket from any hanging queries.
            for query_hash in self.socket_to_queries[socket_id]:
                await self.unsubscribe(socket_id, query_hash)
            # And delete all references to it.
            del self.socket_to_queries[socket_id]
            del self.sockets[socket_id]

    async def subscribe(self, socket_id, query, owner_id):
        # Rewrite
        query_hash, query = query_rewrite(msg['query'], owner_id)

        # If no one is already subbed to the query
        if query_hash not in query_to_sockets:
            # Make sure the query has valid syntax
            # by performing a test query
            await self.db.find_one(query)

        # If no one is *still* not subbed to the query
        # (someone might have during the async call)
        if query_hash not in query_to_sockets:
            # Allocate space for the query internally
            query_to_sockets[query_hash] = set()
            # And tell the broker about the subscription
            await self.request({
                'type': 'subscribe',
                'query_hash': query_hash,
                'query': query,
            })

        # Finally, add the requesting socket to the query
        query_to_sockets[query_hash].add(socket_id)

    async def unsubscribe(self, socket_id, query_hash):
        # Remove the socket from the query
        query_to_sockets[query_hash].remove(socket_id)

        # If the query has no more subs, delete it entirely
        if not len(query_to_sockets(query_hash)):
            del query_to_sockets[query_hash]
            await self.request({
                'type': 'unsubscribe',
                'query_hash': query_hash,
            })

    async def on_results(self, msg):
        print(f"received updates: {msg}")

    async def request(self, msg): 
        await self.initialized.wait()
        await self.channel.default_exchange.publish(
            Message(json.dumps(msg).encode()),
            routing_key=self.request_queue
        )