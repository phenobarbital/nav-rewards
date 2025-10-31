from typing import Union, Any
from collections.abc import Callable, Awaitable
import asyncio
from functools import wraps
from aiohttp import web
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611 # noqa
from navconfig.utils.types import Singleton
from navconfig.logging import logging
import aiormq
from navigator_session import get_session
from navigator_auth.conf import (
    AUTH_SESSION_OBJECT
)
from navigator.applications.base import BaseApplication
from navigator.types import WebApp
from ..conf import (
    rabbitmq_dsn,
    EVENT_MANAGER_QUEUE_SIZE
)


# Disable Debug Logging for AIORMQ
logging.getLogger('aiormq').setLevel(logging.WARNING)


class EventManager(metaclass=Singleton):
    """
    EventManager.
        Universal Event Manager for Navigator.
    """
    def __init__(self, dsn: str = None, workers: int = 3):
        self.rabbitmq_dsn: str = dsn or rabbitmq_dsn
        self.connection = None
        self.channel = None
        self.timeout: int = 5
        self.logger = logging.getLogger('Rewards.EventManager')
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 1  # Initial delay in seconds
        self.event_queue = asyncio.Queue(maxsize=EVENT_MANAGER_QUEUE_SIZE)
        self._workers = workers

    def setup(self, app: web.Application = None) -> None:
        """
        Setup EventManager.
        """
        if isinstance(app, BaseApplication):
            self.app = app.get_app()
        elif isinstance(app, WebApp):
            self.app = app  # register the app into the Extension

        app.on_startup.append(self.open)
        app.on_shutdown.append(self.close)
        if app:
            app['event_manager'] = self
        else:
            raise ValueError(
                'App is not defined.'
            )
        ## Generic Event Subscription:
        app.router.add_post(
            '/api/v1/events/publish_event',
            self.event_publisher
        )

    async def start_workers(self):
        for i in range(self._workers):
            asyncio.create_task(
                self._event_worker(i)
            )

    async def _event_worker(self, worker_id: int):
        while True:
            # Wait for an event to be available in the queue
            event = await self.event_queue.get()
            try:
                # data:
                routing = event.get('routing_key')
                exchange = event.get('exchange')
                body = event.get('body')
                # Publish the event to RabbitMQ
                await self._publish_event(
                    exchange=exchange,
                    routing_key=routing,
                    body=body
                )
                self.logger.info(
                    f"Worker {worker_id} published event: {routing}"
                )
            except Exception as e:
                self.logger.error(
                    f"Error publishing event: {e}"
                )
            finally:
                self.event_queue.task_done()

    async def get_userid(self, session, idx: str = 'user_id') -> int:
        try:
            if AUTH_SESSION_OBJECT in session:
                return session[AUTH_SESSION_OBJECT][idx]
            else:
                return session[idx]
        except KeyError as e:
            raise RuntimeError(
                'User ID is not found in the session.'
            ) from e

    @staticmethod
    def service_auth(
        fn: Callable[..., Awaitable[Any]]
    ) -> Callable[..., Awaitable[Any]]:
        @wraps(fn)
        async def _wrap(self, request: web.Request, *args, **kwargs) -> Any:
            ## get User Session:
            try:
                session = await get_session(request)
            except (ValueError, RuntimeError) as err:
                raise web.HTTPUnauthorized(
                    reason=str(err)
                )
            if session:
                self._userid = await self.get_userid(session)
            # Perform your session and user ID checks here
            if not self._userid:
                raise web.HTTPUnauthorized(
                    reason="User ID not found in session"
                )
            # TODO: Checking User Permissions:
            return await fn(self, request, *args, **kwargs)
        return _wrap

    async def open(self, app: web.Application) -> None:
        await self.connect()
        # Start the workers
        await self.start_workers()

    async def close(self, app: web.Application) -> None:
        # Wait for all events to be processed
        await self.event_queue.join()
        # then, close the RabbitMQ connection
        await self.disconnect()

    async def connect(self) -> None:
        try:
            self.logger.debug(
                f":: Connecting to RabbitMQ: {self.rabbitmq_dsn}"
            )
            self.connection = await asyncio.wait_for(
                aiormq.connect(
                    self.rabbitmq_dsn
                ),
                timeout=self.timeout
            )
            self.reconnect_attempts = 0
            self.channel = await self.connection.channel()
            await self.start_connection_monitor()
        except asyncio.TimeoutError as e:
            print("Connection timed out")
            raise RuntimeError(
                "Connection timed out"
            ) from e
        except Exception as err:
            self.logger.error(
                f"Error while connecting to RabbitMQ: {err}"
            )
            await self.schedule_reconnect()

    async def disconnect(self) -> None:
        if self.channel is not None:
            try:
                await self.channel.close()
                self.channel = None
            except Exception as err:
                self.logger.warning(
                    f"Error while closing channel: {err}"
                )
        if self.connection is not None:
            try:
                await self.connection.close()
                self.connection = None
            except Exception as err:
                self.logger.warning(
                    f"Error while closing connection: {err}"
                )

    async def start_connection_monitor(self):
        """Start a background task to monitor the RabbitMQ connection."""
        asyncio.create_task(
            self.connection_monitor()
        )

    async def connection_monitor(self):
        """Monitor the RabbitMQ connection and
            attempt to reconnect if disconnected.
        """
        while True:
            if not self.connection or self.connection.is_closed:
                self.logger.warning(
                    "Connection lost. Attempting to reconnect..."
                )
                await self.connect()
            await asyncio.sleep(60)  # Check every 60 seconds

    async def schedule_reconnect(self):
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            delay = self.reconnect_delay * (
                2 ** (self.reconnect_attempts - 1)
            )  # Exponential backoff
            self.logger.info(
                f"Scheduling reconnect in {delay} seconds..."
            )
            await asyncio.sleep(delay)
            await self.connect()
        else:
            self.logger.error(
                "Max reconnect attempts reached. Giving up."
            )

    @service_auth
    async def event_publisher(
        self,
        request: web.Request
    ) -> web.Response:
        """
        Event Publisher.
        """
        data = await request.json()
        exc = data.get('exchange', 'navigator')
        event_name = data.get('event')
        if not event_name:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'routing_key is required.'
                },
                status=422
            )
        body = data.get('body')
        if not body:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'body is required.'
                },
                status=422
            )
        await self.publish_event(exc, event_name, body)
        return web.json_response({
            'status': 'success',
            'message': f'Event {exc}.{event_name} Published Successfully.'
        })

    async def subcribe_callback(
        self,
        message: aiormq.abc.DeliveredMessage,
        callback: Union[Callable, Awaitable]
    ) -> None:
        """
        Default Callback for Event Subscription.
        """
        body = message.body.decode('utf-8')
        if asyncio.iscoroutinefunction(callback):
            await callback(message, body)
        else:
            callback(message, body)

    async def publish_event(
        self,
        exchange: str,
        routing_key: str,
        body: str,
        **kwargs
    ) -> None:
        """
        Publish Event on a Worker.
        """
        try:
            await self.event_queue.put(
                {
                    'exchange': exchange,
                    'routing_key': routing_key,
                    'body': body
                }
            )
        except asyncio.QueueFull:
            self.logger.error(
                "Event queue is full. Event will not published."
            )

    async def create_exchange(
        self,
        exchange_name: str,
        exchange_type: str = 'topic',
        durable: bool = True
    ):
        """
        Declare an exchange on RabbitMQ.
        """
        if not self.channel:
            self.logger.error(
                "RabbitMQ channel is not established."
            )
            return

        try:
            await self.channel.exchange_declare(
                exchange=exchange_name,
                exchange_type=exchange_type,
                durable=durable
            )
            self.logger.info(
                f"Exchange '{exchange_name}' declared successfully."
            )
        except Exception as e:
            self.logger.error(
                f"Failed to declare exchange '{exchange_name}': {e}"
            )

    async def ensure_exchange(
        self,
        exchange_name: str,
        exchange_type: str = 'topic',
        **kwargs
    ) -> None:
        """
        Ensure that the specified exchange exists in RabbitMQ.
        """
        args = {
            "durable": True,
            **kwargs
        }
        try:
            await self.channel.exchange_declare(
                exchange=exchange_name,
                exchange_type=exchange_type,
                **args
            )
        except Exception as err:
            self.logger.error(
                f"Error declaring exchange: {err}"
            )

    async def _publish_event(
        self,
        exchange: str,
        routing_key: str,
        body: str,
        **kwargs
    ) -> None:
        """
        Publish Event on a rabbitMQ Exchange.
        """
        # Ensure the exchange exists before publishing
        await self.ensure_exchange(exchange)

        args = {
            "mandatory": True,
            **kwargs
        }
        if isinstance(body, (dict, list)):
            body = json_encoder(body)

        await self.channel.basic_publish(
            body.encode('utf-8'),
            exchange=exchange,
            routing_key=routing_key,
            **args
        )

    async def event_subscribe(
        self,
        queue_name: str,
        callback: Union[Callable, Awaitable]
    ) -> None:
        """Event Subscribe.
        """
        await self.channel.queue_declare(queue_name)
        await self.channel.basic_consume(queue_name, callback)

    async def subscribe_to_events(
        self,
        exchange: str,
        queue_name: str,
        routing_key: str,
        callback: Callable
    ) -> None:
        """
        Subscribe to events from a specific exchange with a given routing key.
        """
        # Declare the queue
        await self.channel.queue_declare(queue_name, durable=True)

        # Bind the queue to the exchange
        await self.channel.queue_bind(
            queue=queue_name,
            exchange=exchange,
            routing_key=routing_key
        )

        # Start consuming messages from the queue
        await self.channel.basic_consume(
            queue=queue_name,
            consumer_callback=self.wrap_callback(callback),
        )

    def wrap_callback(self, callback: Callable) -> Callable:
        """
        Wrap the user-provided callback to handle message decoding and
        acknowledgment.
        """
        async def wrapped_callback(message: aiormq.abc.DeliveredMessage):
            body = message.body.decode('utf-8')
            await callback(message, body)
            # Acknowledge the message to indicate it has been processed
            await self.channel.basic_ack(message.delivery.delivery_tag)
        return wrapped_callback
