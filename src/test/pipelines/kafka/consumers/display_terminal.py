import os, json
from kafka import KafkaConsumer
from rich.console import Console
from rich.live import Live
from rich.table import Table

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "deepcare")
TOPIC = f"{TOPIC_PREFIX}.sensor-events"

def make_table(state):
    tbl = Table(title=f"Live Sensors — {TOPIC}", expand=True)
    for col in ["Device","Temp (°C)","Humid (%)","Noise (dB)","PM1","PM2.5","PM10","PIR","Updated"]:
        tbl.add_column(col)
    for dev, ev in sorted(state.items()):
        s = ev.get("sensors", {})
        ts = ev.get("ts", "")
        def fmt(x): 
            return "" if x is None else (f"{x:.1f}" if isinstance(x,(int,float)) else str(x))
        tbl.add_row(
            dev,
            fmt(s.get("temp")), fmt(s.get("humid")), fmt(s.get("noise")),
            fmt(s.get("pm1")), fmt(s.get("pm25")), fmt(s.get("pm10")),
            "🟢" if s.get("pir") in (1, True, "1", "true") else "⚫",
            ts.replace("T"," ").split("+")[0]
        )
    return tbl

def main():
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        enable_auto_commit=False,
        auto_offset_reset=os.getenv("AUTO_OFFSET_RESET","latest"),
        value_deserializer=lambda b: json.loads(b.decode("utf-8", errors="ignore"))
    )
    console = Console()
    state = {}
    with Live(make_table(state), console=console, refresh_per_second=4):
        for m in consumer:
            ev = m.value
            dev = ev.get("device_id","?")
            state[dev] = ev
            # table refreshes automatically

if __name__ == "__main__":
    main()
