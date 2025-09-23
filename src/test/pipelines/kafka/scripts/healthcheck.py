import os
import logging
from kafka import KafkaConsumer

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper(), format="%(message)s")
logger = logging.getLogger("healthcheck")

def main():
    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    logger.info("Connecting to Kafka at %s ...", bootstrap)
    consumer = KafkaConsumer(bootstrap_servers=bootstrap, group_id=None, request_timeout_ms=10000)
    topics = consumer.topics()
    logger.info("Connected. Topic count: %d", len(topics))
    for t in sorted(topics):
        logger.info(" - %s", t)
    consumer.close()

if __name__ == "__main__":
    main()
