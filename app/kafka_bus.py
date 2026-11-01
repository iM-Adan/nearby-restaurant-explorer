import json
import logging
import threading
from typing import Dict, Any, Optional, Callable
from app.config import settings

logger = logging.getLogger("kafka_bus")

try:
    from kafka import KafkaProducer, KafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

class AsyncKafkaManager:
    """
    Handles asynchronous Kafka event production and consumption for:
      1. Restaurant ingestion / bulk updates -> live 2-D Tree update & cache invalidation
      2. Spatial search query analytics -> non-blocking latency & cache-hit logging
    Includes a seamless in-process async queue fallback when running tests without a broker.
    """

    def __init__(
        self,
        on_restaurant_ingested: Callable[[Dict[str, Any]], None],
        on_analytics_logged: Callable[[Dict[str, Any]], None],
    ):
        self.on_restaurant_ingested = on_restaurant_ingested
        self.on_analytics_logged = on_analytics_logged
        self.producer: Optional[Any] = None
        self.connected: bool = False
        self._stop_event = threading.Event()
        self._consumer_thread: Optional[threading.Thread] = None
        self.published_events = 0
        self.consumed_events = 0

    def start(self) -> None:
        if not KAFKA_AVAILABLE:
            logger.warning("kafka-python-ng not installed; using in-process async fallback.")
            return
        try:
            self.producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                request_timeout_ms=3000,
                max_block_ms=3000,
            )
            self.connected = True
            self._consumer_thread = threading.Thread(
                target=self._consume_loop, daemon=True, name="kafka-consumer-worker"
            )
            self._consumer_thread.start()
            logger.info("Connected to Kafka broker at %s", settings.KAFKA_BOOTSTRAP_SERVERS)
        except Exception as exc:
            logger.warning("Kafka broker unreachable (%s). Falling back to background thread dispatch.", exc)
            self.connected = False

    def stop(self) -> None:
        self._stop_event.set()
        if self.producer:
            try:
                self.producer.close(timeout=2)
            except Exception:
                pass

    def publish_restaurant_ingestion(self, payload: Dict[str, Any]) -> str:
        self.published_events += 1
        if self.connected and self.producer:
            try:
                self.producer.send(settings.KAFKA_INGEST_TOPIC, value=payload)
                self.producer.flush(timeout=2.0)
                return "KAFKA_BROKER"
            except Exception as exc:
                logger.error("Kafka publish error: %s", exc)

        # Fallback asynchronous worker so API remains non-blocking
        threading.Thread(target=self._fallback_ingest, args=(payload,), daemon=True).start()
        return "ASYNC_LOCAL_FALLBACK"

    def publish_search_analytics(self, metrics: Dict[str, Any]) -> None:
        self.published_events += 1
        if self.connected and self.producer:
            try:
                self.producer.send(settings.KAFKA_ANALYTICS_TOPIC, value=metrics)
                return
            except Exception:
                pass
        threading.Thread(target=self._fallback_analytics, args=(metrics,), daemon=True).start()

    def _fallback_ingest(self, payload: Dict[str, Any]) -> None:
        self.consumed_events += 1
        self.on_restaurant_ingested(payload)

    def _fallback_analytics(self, metrics: Dict[str, Any]) -> None:
        self.consumed_events += 1
        self.on_analytics_logged(metrics)

    def _consume_loop(self) -> None:
        try:
            consumer = KafkaConsumer(
                settings.KAFKA_INGEST_TOPIC,
                settings.KAFKA_ANALYTICS_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                group_id="nearby-restaurant-explorer-group",
                auto_offset_reset="latest",
                consumer_timeout_ms=1000,
            )
            while not self._stop_event.is_set():
                for msg in consumer:
                    if self._stop_event.is_set():
                        break
                    self.consumed_events += 1
                    if msg.topic == settings.KAFKA_INGEST_TOPIC:
                        self.on_restaurant_ingested(msg.value)
                    elif msg.topic == settings.KAFKA_ANALYTICS_TOPIC:
                        self.on_analytics_logged(msg.value)
            consumer.close()
        except Exception as exc:
            logger.warning("Kafka consumer loop terminated: %s", exc)
