import os, json
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "deepcare")
TOPIC = f"{TOPIC_PREFIX}.sensor-events"

def main():
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        enable_auto_commit=False,
        auto_offset_reset=os.getenv("AUTO_OFFSET_RESET","latest"),  # 'earliest' or 'latest'
        value_deserializer=lambda b: json.loads(b.decode("utf-8", errors="ignore"))
    )
    print(f"Listening Kafka {BOOTSTRAP} topic={TOPIC} ... (Ctrl+C to stop)")
    for m in consumer:
        print(json.dumps(m.value, ensure_ascii=False))

if __name__ == "__main__":
    main()
