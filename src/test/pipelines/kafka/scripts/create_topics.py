import os
import logging
import yaml
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper(), format="%(message)s")
logger = logging.getLogger("create_topics")

def main():
    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "topics.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    prefix = cfg.get("prefix","deepcare")
    topics_cfg = cfg.get("topics", [])

    admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="topic-admin")
    existing = set(admin.list_topics())

    create_reqs = []
    for t in topics_cfg:
        name = f"{prefix}.{t['name']}"
        if name in existing:
            logger.info("Topic exists: %s", name)
            continue
        partitions = int(t.get("partitions", 1))
        rf = int(t.get("replication_factor", 1))
        config = t.get("config", {})
        create_reqs.append(NewTopic(name=name, num_partitions=partitions, replication_factor=rf, topic_configs=config))

    if not create_reqs:
        logger.info("No topics to create.")
        return

    try:
        admin.create_topics(new_topics=create_reqs, validate_only=False)
        for nt in create_reqs:
            logger.info("Created: %s", nt.name)
    except TopicAlreadyExistsError:
        logger.info("Some topics already exist; nothing to do.")
    finally:
        admin.close()

if __name__ == "__main__":
    main()
