import os, json, threading, asyncio
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "deepcare")
TOPIC = f"{TOPIC_PREFIX}.sensor-events"

app = FastAPI(title="Sensor Live Dashboard")
queue: asyncio.Queue = asyncio.Queue()

@app.get("/")
async def index():
    html = """
    <!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Sensor Live Dashboard</title>
    <style>body{font-family:system-ui,Arial;margin:16px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}.card{border:1px solid #ddd;border-radius:12px;padding:12px}.k{color:#666;font-size:12px;text-transform:uppercase}.v{font-weight:600;font-size:18px}.ts{color:#888;font-size:12px}.pir{font-size:12px;padding:2px 6px;border-radius:10px;display:inline-block}.on{background:#22c55e33;color:#166534}.off{background:#e5e7eb;color:#374151}</style>
    </head><body>
    <h1>Sensor Live Dashboard (<span id="topic"></span>)</h1><div class="grid" id="grid"></div>
    <script>
      const topic = %r; document.getElementById('topic').textContent = topic;
      const grid = document.getElementById('grid'); const state = new Map();
      function fmt(x){return (x==null||x===undefined)?'':(typeof x==='number'?x.toFixed(1):String(x));}
      function on(v){return (v===1||v===true||v==='1'||v==='true');}
      function render(){
        grid.innerHTML='';
        for(const [dev,ev] of state.entries()){
          const s = ev.sensors||{}; const ts=(ev.ts||'').replace('T',' ').split('+')[0];
          const card = document.createElement('div'); card.className='card';
          card.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center">
              <div style="font-weight:700">${dev}</div><div class="ts">${ts}</div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:8px">
              <div><div class="k">Temp</div><div class="v">${fmt(s.temp)}</div></div>
              <div><div class="k">Humid</div><div class="v">${fmt(s.humid)}</div></div>
              <div><div class="k">Noise</div><div class="v">${fmt(s.noise)}</div></div>
              <div><div class="k">PM1</div><div class="v">${fmt(s.pm1)}</div></div>
              <div><div class="k">PM2.5</div><div class="v">${fmt(s.pm25)}</div></div>
              <div><div class="k">PM10</div><div class="v">${fmt(s.pm10)}</div></div>
            </div>
            <div style="margin-top:8px"><span class="pir ${on(s.pir)?'on':'off'}">${on(s.pir)?'PIR ON':'PIR OFF'}</span></div>`;
          grid.appendChild(card);
        }
      }
      const ws = new WebSocket(`ws://${location.host}/ws`);
      ws.onmessage = ev => { const msg = JSON.parse(ev.data); state.set(msg.device_id||'?', msg); render(); };
    </script></body></html>
    """ % (TOPIC,)
    return HTMLResponse(html)

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = await queue.get()
            await ws.send_text(msg)
    except WebSocketDisconnect:
        pass

def kafka_thread():
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        enable_auto_commit=False,
        auto_offset_reset=os.getenv("AUTO_OFFSET_RESET","latest"),
        value_deserializer=lambda b: b.decode("utf-8","ignore")
    )
    for m in consumer:
        asyncio.run(queue.put(m.value))

def main():
    threading.Thread(target=kafka_thread, daemon=True).start()
    uvicorn.run("pipelines.kafka.consumers.ws_dashboard:app", host=os.getenv("WS_HOST","0.0.0.0"), port=int(os.getenv("WS_PORT","8001")), log_level="info")

if __name__ == "__main__":
    main()
